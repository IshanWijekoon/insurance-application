import Link from "next/link";

function DemoCreds({ email, password }: { email: string; password: string }) {
  return (
    <div className="mt-6 rounded-xl border border-white/10 bg-navy-950/60 px-3 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Demo login</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <code className="rounded-lg bg-white/10 px-2.5 py-1 font-mono text-xs text-white">{email}</code>
        <code className="rounded-lg bg-white/10 px-2.5 py-1 font-mono text-xs text-white">{password}</code>
      </div>
    </div>
  );
}

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-navy-950 text-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent-500 text-sm font-bold text-navy-950">AC</span>
          <span className="font-semibold">Aether Cover</span>
        </div>
      </header>
      <section className="mx-auto max-w-6xl px-6 pb-20 pt-10">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent-400">Motor insurance</p>
        <h1 className="mt-4 text-4xl font-semibold leading-tight md:text-5xl">
          Two portals. Two jobs. The client reports. The agent reviews.
        </h1>
        <p className="mt-6 max-w-3xl text-base leading-relaxed text-slate-300 md:text-lg">
          Operations are separate on purpose. Clients never decide a claim. Agents never file the client’s report.
        </p>
        <div className="mt-14 grid gap-6 md:grid-cols-2">
          <div className="flex flex-col rounded-2xl border border-white/10 bg-navy-800 p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent-400">Client portal</p>
            <h2 className="mt-3 text-2xl font-semibold text-white">Report an accident</h2>
            <ul className="mt-5 space-y-2.5 text-sm leading-relaxed text-slate-200">
              <li>Photograph the vehicle and the damage</li>
              <li>Describe what happened</li>
              <li>Submit the report and wait for an agent</li>
            </ul>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/login" className="btn-accent">Client sign in</Link>
              <Link href="/register" className="btn-ghost !border-white/20 !bg-transparent !text-white hover:!bg-white/10">
                Create client account
              </Link>
            </div>
            <DemoCreds email="customer@insure.local" password="ChangeMe123!" />
          </div>
          <div className="flex flex-col rounded-2xl border border-white/10 bg-navy-800 p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent-400">Agent portal</p>
            <h2 className="mt-3 text-2xl font-semibold text-white">Review client reports</h2>
            <ul className="mt-5 space-y-2.5 text-sm leading-relaxed text-slate-200">
              <li>Watch incoming client reports</li>
              <li>Verify photos, cost, location and time</li>
              <li>Record the authorised insurance decision</li>
            </ul>
            <div className="mt-8">
              <Link href="/login/agent" className="btn-accent">Agent sign in</Link>
            </div>
            <DemoCreds email="agent@insure.local" password="ChangeMe123!" />
          </div>
        </div>
      </section>
    </div>
  );
}
