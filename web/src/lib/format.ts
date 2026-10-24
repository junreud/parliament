export const TOPICS: Record<string, string> = { housing: "주거", labor: "노동", "economy-tax": "경제·세금", family: "가족·양육" };
export const STAGES: Record<string, string> = { announced: "발표", scheduled: "일정", proposed: "발의", reviewing: "심사 중", voted: "표결", passed: "의결", rejected: "부결", alternative: "대안 반영", withdrawn: "철회", promulgated: "공포", effective: "시행", unknown: "단계 미확인" };
export const TYPES: Record<string, string> = { bill: "법안", vote: "표결", announcement: "공식 발표", speech: "발언", meeting: "회의", law: "법령" };
export const VOTE_RESULTS: Record<string, string> = { yes: "찬성", no: "반대", abstain: "기권", absent: "불참", unknown: "개인별 기록 미확인" };
export function dateLabel(value: string | null | undefined): string {
  if (!value || Number.isNaN(new Date(value).getTime())) return "미확인";
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}
export function safeSource(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const official = ["assembly.go.kr", "president.go.kr", "opm.go.kr", "korea.kr", "law.go.kr", "lawmaking.go.kr", "nanet.go.kr", "mogef.go.kr", "nec.go.kr", "org.go.kr", "gaok.or.kr", "namk.or.kr", "mcee.go.kr", "mods.go.kr", "mofe.go.kr", "moj.go.kr", "naacc.go.kr", "pipc.go.kr", "acrc.go.kr", "bai.go.kr", "cio.go.kr", "customs.go.kr", "dapa.go.kr", "forest.go.kr", "fsc.go.kr", "ftc.go.kr", "humanrights.go.kr", "kasa.go.kr", "kcg.go.kr", "kdca.go.kr", "khs.go.kr", "kmcc.go.kr", "mafra.go.kr", "mcst.go.kr", "mfds.go.kr", "mma.go.kr", "mnd.go.kr", "moe.go.kr", "moel.go.kr", "mof.go.kr", "mohw.go.kr", "moip.go.kr", "mois.go.kr", "moleg.go.kr", "molit.go.kr", "motir.go.kr", "mpb.go.kr", "mpm.go.kr", "mpva.go.kr", "msit.go.kr", "mss.go.kr", "ne.go.kr", "nfa.go.kr", "nis.go.kr", "nssc.go.kr", "nts.go.kr", "oka.go.kr", "police.go.kr", "pps.go.kr", "rda.go.kr", "saemangeum.go.kr", "spo.go.kr", "unikorea.go.kr", "weather.go.kr"];
    return url.protocol === "https:" && !url.username && !url.password && !url.hash && (!url.port || url.port === "443") && (["www.hscity.go.kr", "balance.go.kr", "www.balance.go.kr"].includes(url.hostname) || [...official, "mofa.go.kr", "jejusi.go.kr", "seogwipo.go.kr", "goryeong.go.kr", "jeju.go.kr", "pss.go.kr", "kma.go.kr", "neac.go.kr", "pacst.go.kr", "puac.go.kr", "ktv.go.kr"].some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))) ? url.href : null;
  } catch { return null; }
}
