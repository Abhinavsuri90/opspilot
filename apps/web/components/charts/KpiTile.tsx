import type { KpiTileModel, KpiTone } from "@/lib/metrics";

const dots: Record<KpiTone, string> = {
  primary: "bg-cyan-600",
  review: "bg-amber-500",
  completed: "bg-emerald-600",
  neutral: "bg-slate-400",
};

/** One KPI: label, the value (or a quiet dash), a one-line detail, and the definition as a tooltip. */
export function KpiTile({ tile }: { tile: KpiTileModel }) {
  const long = tile.value.length > 9;
  return <div role="group" aria-label={tile.label} title={tile.definition} data-testid={`kpi-${tile.id}`} data-empty={tile.empty ? "true" : "false"} className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-[0_6px_20px_rgba(15,23,42,.035)] sm:p-5">
    <div className="flex items-start justify-between gap-2">
      <p className="text-xs font-semibold text-slate-600">{tile.label}</p>
      <span aria-hidden="true" className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dots[tile.tone]}`} />
    </div>
    <p data-testid="kpi-value" className={`font-bold tracking-[-.04em] ${long ? "mt-3 text-lg leading-6" : "mt-3 text-[28px] leading-none"} ${tile.empty ? "text-slate-400" : "text-[#12233d]"}`}>{tile.value}</p>
    <p className="mt-2 text-xs leading-5 text-slate-500">{tile.detail}</p>
  </div>;
}

/** The KPI row: seven tiles that wrap from one column on a phone to four on a wide screen. */
export function KpiTiles({ tiles, loading = false }: { tiles: KpiTileModel[]; loading?: boolean }) {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" aria-busy={loading || undefined}>
    {tiles.map(tile => <KpiTile key={tile.id} tile={tile} />)}
  </div>;
}
