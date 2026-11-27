// CreditsMeter (Datamart Warmup): the AI credit gauge in the top header.
//
// Replaces upstream's meter, which only runs with a billing provider. Here the
// backend (datamart/go/datamart_allowance.go) reports the free allowance as
// the plan pool and one-time credit packs as the purchased pool. The trigger
// shows free credits left plus "+N" paid; the panel explains both and links
// to the credit packs page served by datamart/billing at /molty/credits.

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRightIcon } from "lucide-react";
import useClickOutside from "@/hooks/useClickOutside";
import AnimatedNumber from "@/components/ui/AnimatedNumber";
import getCredits from "@/lib/api/client/app/subscription/getCredits";
import type { CreditBalance } from "@/lib/api/models/app/subscription/Credits";
import { usePermission } from "@/hooks/usePermission";
import { DitherMeter } from "@/components/ui/dither";
import { cn } from "@/lib/utils";

type DatamartCredits = CreditBalance & {
    free_period?: "day" | "month";
    free_used?: number;
    buy_url?: string;
};

export function CreditsMeter() {
    const canSee = usePermission("MANAGE_BILLING");
    // No realtime event carries a free credit spend, so the meter refreshes
    // itself while the tab is visible.
    const credits = useQuery({
        queryKey: ["subscription", "credits"],
        queryFn: () => getCredits() as Promise<DatamartCredits>,
        staleTime: 15_000,
        refetchInterval: 30_000,
        enabled: canSee,
    });
    const [open, setOpen] = React.useState(false);
    const ref = React.useRef<HTMLDivElement>(null);
    const close = React.useCallback(() => setOpen(false), []);
    useClickOutside(open, close, ref);

    const c = credits.data as DatamartCredits | undefined;
    if (!canSee || !c || c.unlimited) return null;

    const free = c.monthly_balance;
    const limit = c.monthly_allowance;
    const paid = c.purchased_balance;
    const empty = c.balance <= 0;
    const low = !empty && paid === 0 && free <= Math.max(1, Math.round(limit / 5));
    const fraction = limit > 0 ? Math.min(1, free / limit) : 0;
    const period = c.free_period === "month" ? "this month" : "today";
    const label = `${free.toLocaleString()} of ${limit.toLocaleString()} free AI credits left ${period}${
        paid > 0 ? `, plus ${paid.toLocaleString()} paid` : ""
    }`;

    return (
        <div ref={ref} className="relative">
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                aria-label={label}
                aria-expanded={open}
                title={open ? undefined : label}
                className={cn(
                    "flex items-center gap-1.5 px-2 h-7 rounded-md text-[11.5px] font-medium tabular-nums transition-colors",
                    empty
                        ? "text-red-600 hover:bg-red-50"
                        : low
                          ? "text-amber-600 hover:bg-amber-50"
                          : "text-slate-500 hover:text-slate-900 hover:bg-slate-200/60",
                )}
            >
                <Ring fraction={paid > 0 ? 1 : fraction} />
                <span className="flex items-baseline">
                    <AnimatedNumber value={free} format={(n) => formatCredits(Math.round(n))} />
                    <span className="opacity-60 font-normal">/{formatCredits(limit)}</span>
                </span>
                {paid > 0 && <span className="opacity-70 font-normal">+{formatCredits(paid)}</span>}
            </button>

            <AnimatePresence>
                {open && (
                    <motion.div
                        initial={{ opacity: 0, y: -4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        transition={{ duration: 0.12 }}
                        className="absolute right-0 top-full mt-1.5 w-72 rounded-md border border-slate-200 bg-white shadow-[0_12px_32px_-8px_rgba(15,23,42,0.18)] z-50 overflow-hidden"
                    >
                        <Panel credits={c} empty={empty} low={low} />
                        {c.buy_url && (
                            <a
                                href={c.buy_url}
                                onClick={close}
                                className="flex items-center gap-1 px-3 h-9 border-t border-slate-200 text-[11.5px] font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-50 transition-colors"
                            >
                                Buy more credits
                                <ArrowUpRightIcon className="w-3 h-3" />
                            </a>
                        )}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}

function Panel({ credits, empty, low }: { credits: DatamartCredits; empty: boolean; low: boolean }) {
    const monthly = credits.free_period === "month";
    const free = credits.monthly_balance;
    const limit = credits.monthly_allowance;
    const used = credits.free_used ?? Math.max(0, limit - free);
    const paid = credits.purchased_balance;

    return (
        <div className="px-3 pt-3 pb-2.5 space-y-3.5">
            <div className="flex items-end justify-between">
                <div>
                    <div className="text-[10px] uppercase tracking-[0.14em] text-slate-400 font-medium">
                        AI credits
                    </div>
                    <div className="mt-1 flex items-baseline gap-1.5">
                        <AnimatedNumber
                            value={credits.balance}
                            className={cn(
                                "text-[22px] leading-none font-semibold tracking-tight tabular-nums",
                                empty ? "text-red-600" : "text-slate-900",
                            )}
                        />
                        <span className="text-[11px] text-slate-400">left</span>
                    </div>
                </div>
                {(empty || low) && (
                    <div
                        className={cn(
                            "flex items-center gap-1.5 text-[10.5px] font-medium pb-0.5",
                            empty ? "text-red-600" : "text-amber-600",
                        )}
                    >
                        <span className={cn("size-1.5 rounded-full shrink-0", empty ? "bg-red-500" : "bg-amber-500")} />
                        {empty ? "Out of credits" : "Running low"}
                    </div>
                )}
            </div>

            <div>
                <div className="flex items-baseline justify-between text-[11.5px]">
                    <span className="text-slate-600">{monthly ? "Included this month" : "Free today"}</span>
                    <span className="tabular-nums text-slate-900 font-medium">
                        {free.toLocaleString()}
                        <span className="text-slate-400 font-normal"> / {limit.toLocaleString()}</span>
                    </span>
                </div>
                <DitherMeter
                    frac={limit > 0 ? Math.min(1, Math.max(0, free / limit)) : 0}
                    tone={free <= 0 ? "rose" : low ? "amber" : "slate"}
                    height={4}
                    className="mt-1.5"
                />
                <div className="mt-1 flex justify-between text-[10.5px] text-slate-400">
                    <span>
                        {used.toLocaleString()} used {monthly ? "this month" : "today"}
                    </span>
                    <span>{resetLabel(credits.next_reset_at, monthly)}</span>
                </div>
            </div>

            <div>
                <div className="flex items-baseline justify-between text-[11.5px]">
                    <span className="text-slate-600">Paid credits</span>
                    <span className={cn("tabular-nums font-medium", paid > 0 ? "text-slate-900" : "text-slate-400")}>
                        {paid.toLocaleString()}
                        <span className="text-slate-400 font-normal"> never expire</span>
                    </span>
                </div>
                <p className="mt-1 text-[10.5px] text-slate-400">
                    Used once the {monthly ? "included" : "free"} credits run out.
                </p>
            </div>
        </div>
    );
}

// Small ring gauge drawn with currentColor so it follows the trigger's text color.
function Ring({ fraction }: { fraction: number }) {
    const r = 5.5;
    const circumference = 2 * Math.PI * r;
    return (
        <svg viewBox="0 0 14 14" className="w-3.5 h-3.5 -rotate-90 shrink-0" aria-hidden>
            <circle cx="7" cy="7" r={r} fill="none" stroke="currentColor" strokeWidth="2" opacity="0.2" />
            <circle
                cx="7"
                cy="7"
                r={r}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={circumference * (1 - Math.max(0, Math.min(1, fraction)))}
                className="transition-[stroke-dashoffset] duration-300"
            />
        </svg>
    );
}

// formatCredits keeps the trigger compact: 843, 12.4k, 1.2M.
function formatCredits(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
    if (n >= 10_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
    return n.toLocaleString();
}

function resetLabel(iso: string | Date | null, monthly: boolean): string {
    if (!monthly || !iso) return "Resets at midnight UTC";
    const d = new Date(iso);
    return `Resets ${d.toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" })}`;
}
