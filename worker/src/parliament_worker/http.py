"""Bounded HTTPS fetching with an exact host allowlist checked on every hop."""

import ipaddress
import socket
import time
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

OFFICIAL_HOSTS = frozenset(
    {
        "president.go.kr",
        "www.president.go.kr",
        "opm.go.kr",
        "www.opm.go.kr",
        "korea.kr",
        "www.korea.kr",
        "open.assembly.go.kr",
        "likms.assembly.go.kr",
        "www.assembly.go.kr",
        "record.assembly.go.kr",
        "opinion.lawmaking.go.kr",
        "ampos.nanet.go.kr",
        "www.mogef.go.kr",
        "mogef.go.kr",
        "law.go.kr",
        "www.law.go.kr",
        "clik.nanet.go.kr",
        "www.nec.go.kr",
        "www.org.go.kr",
        "org.go.kr",
        "namk.or.kr",
        "www.namk.or.kr",
        "gaok.or.kr",
        "www.gaok.or.kr",
        "mcee.go.kr",
        "mods.go.kr",
        "mofe.go.kr",
        "mojhome.moj.go.kr",
        "naacc.go.kr",
        "pipc.go.kr",
        "www.acrc.go.kr",
        "www.bai.go.kr",
        "www.cio.go.kr",
        "www.customs.go.kr",
        "www.dapa.go.kr",
        "www.forest.go.kr",
        "www.fsc.go.kr",
        "www.ftc.go.kr",
        "www.humanrights.go.kr",
        "www.kasa.go.kr",
        "www.kcg.go.kr",
        "www.kdca.go.kr",
        "www.khs.go.kr",
        "www.kmcc.go.kr",
        "www.mafra.go.kr",
        "www.mcst.go.kr",
        "www.mfds.go.kr",
        "www.mma.go.kr",
        "www.mnd.go.kr",
        "www.moe.go.kr",
        "www.moel.go.kr",
        "www.mof.go.kr",
        "www.mofa.go.kr",
        "www.mohw.go.kr",
        "www.moip.go.kr",
        "www.mois.go.kr",
        "mois.go.kr",
        "www.moj.go.kr",
        "www.moleg.go.kr",
        "www.molit.go.kr",
        "www.motir.go.kr",
        "www.mpb.go.kr",
        "www.mpm.go.kr",
        "www.mpva.go.kr",
        "www.msit.go.kr",
        "www.mss.go.kr",
        "www.naacc.go.kr",
        "www.ne.go.kr",
        "www.nfa.go.kr",
        "www.nis.go.kr",
        "www.nssc.go.kr",
        "www.nts.go.kr",
        "www.oka.go.kr",
        "www.police.go.kr",
        "www.pps.go.kr",
        "www.rda.go.kr",
        "www.saemangeum.go.kr",
        "www.spo.go.kr",
        "www.unikorea.go.kr",
        "www.weather.go.kr",
        "www.pss.go.kr",
        "humanrights.go.kr",
        "www.kma.go.kr",
        "police.go.kr",
        "www.neac.go.kr",
        "www.pacst.go.kr",
        "www.puac.go.kr",
        "www.ktv.go.kr",
        "www.jejusi.go.kr",
        "jejusi.go.kr",
        "www.seogwipo.go.kr",
        "seogwipo.go.kr",
        "www.goryeong.go.kr",
        "goryeong.go.kr",
        "www.jeju.go.kr",
        "jeju.go.kr",
        "www.hscity.go.kr",
        "balance.go.kr",
        "www.balance.go.kr",
    }
)


def validate_official_url(url: str) -> str:
    """Validate an official HTTPS URL without credentials, fragments or odd ports.

    Args:
        url: Candidate URL from an untrusted source document or redirect header.

    Returns:
        Validated URL, unchanged.

    Raises:
        ValueError: URL escapes the supported public-source boundary.
    """
    parts = urlsplit(url)
    if (
        len(url) > 2048
        or parts.scheme != "https"
        or parts.hostname not in OFFICIAL_HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
        or parts.fragment
    ):
        raise ValueError("unsupported official HTTPS source")
    return url


def resolve_public(host: str) -> list[str]:
    """Resolve an official host using the system resolver."""
    return list({entry[4][0] for entry in socket.getaddrinfo(host, 443)})


class SafeFetcher:
    """Fetch small public responses; redirects never bypass URL/DNS checks."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[[str], list[str]] = resolve_public,
        max_bytes: int = 2_000_000,
        timeout: float = 10.0,
        total_timeout: float = 30.0,
    ) -> None:
        if not 0 < max_bytes <= 10_000_000 or not 0 < timeout <= 30:
            raise ValueError("invalid network limits")
        self.client = client or httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            headers={"User-Agent": "ParliamentResearchWorker/0.1"},
        )
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.total_timeout = total_timeout

    def __call__(
        self,
        url: str,
        *,
        data: dict[str, str] | None = None,
        referer: str | None = None,
    ) -> bytes:
        """Read public HTML/JSON with bounded redirects, bytes and wall time.

        Args:
            url: Supported official HTTPS source URL.
            data: Public read-only form parameters for the official board AJAX.
            referer: Optional validated official referring document for attachments.

        Returns:
            Original response bytes without decoding or normalization.
        """
        if referer is not None:
            validate_official_url(referer)
        headers = {"Accept-Encoding": "identity"}
        if referer:
            headers["Referer"] = referer
        deadline = time.monotonic() + self.total_timeout
        for _ in range(4):
            validate_official_url(url)
            host = urlsplit(url).hostname
            addresses = self.resolver(host or "")
            if not addresses or any(
                not ipaddress.ip_address(address).is_global for address in addresses
            ):
                raise ValueError("source must resolve to public addresses")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("fetch time limit exceeded")
            with self.client.stream(
                "POST" if data is not None else "GET",
                url,
                data=data,
                timeout=min(self.timeout, remaining),
                headers=headers,
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect without destination")
                    url = urljoin(url, location)
                    # Do not forward board form parameters through a redirect.
                    data = None
                    continue
                response.raise_for_status()
                if int(response.headers.get("content-length", "0")) > self.max_bytes:
                    raise ValueError("response size exceeds limit")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ValueError("response size exceeds limit")
                    if time.monotonic() > deadline:
                        raise TimeoutError("fetch time limit exceeded")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise ValueError("redirect limit exceeded")

    def close(self) -> None:
        """Close HTTP connections owned by this fetcher."""
        self.client.close()
