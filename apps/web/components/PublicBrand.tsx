import Link from "next/link";

export function PublicBrand({ light = false, className = "" }: { light?: boolean; className?: string }) {
  return <Link href="/" aria-label="OpsPilot home" className={`inline-flex shrink-0 items-center self-start rounded-lg text-[23px] font-extrabold tracking-[-.9px] ${light ? "text-white" : "text-[#122d36]"} ${className}`}>
    <span className={`mr-2.5 grid h-[34px] w-[34px] place-items-center rounded-[10px] ${light ? "bg-[#31554e] text-[#d3e8b8]" : "bg-[#006b60] text-white"}`}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5" /></svg>
    </span>
    OpsPilot<span className={light ? "text-[#b7d59e]" : "text-[#006b60]"}>.</span>
  </Link>;
}
