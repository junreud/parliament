/** Run one baseline and at most three repairs while preserving verification files. */
export async function runBoundedQa({ verify, fix, contract, maxRepairs = 3 }) {
  if (!Number.isInteger(maxRepairs) || maxRepairs < 0 || maxRepairs > 3)
    throw new Error("Repair limit must be between 0 and 3");
  const original = await contract();
  const runs = [];
  for (let repairs = 0; repairs <= maxRepairs; repairs++) {
    if ((await contract()) !== original)
      return { status: "contract-changed", repairs, runs };
    const run = await verify(repairs);
    runs.push(run);
    if ((await contract()) !== original)
      return { status: "contract-changed", repairs, runs };
    if (run.ok) return { status: "passed", repairs, runs };
    if (repairs === maxRepairs) return { status: "failed", repairs, runs };
    if (!(await fix(run, repairs + 1)))
      return { status: "repair-unavailable", repairs: repairs + 1, runs };
  }
}
