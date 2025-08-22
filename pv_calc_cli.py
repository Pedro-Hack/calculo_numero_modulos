#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
import sys
import textwrap

# ---------------- Models ----------------
@dataclass
class Inverter:
    name: str
    mppt_min_v: float
    mppt_max_v: float
    vdc_max: float
    imax_mppt: float
    iscmax_mppt: float
    n_mppt: int

@dataclass
class Module:
    name: str
    wp: float
    vmp: float
    imp: float
    voc: float
    isc: float
    gamma_pmax_pct_per_C: float
    beta_voc_pct_per_C: float
    alpha_isc_pct_per_C: float

# ---------------- Presets ----------------
PRESET_INVERTERS: Dict[str, Inverter] = {
    "aeg4200": Inverter(
        name="AEG AS-IR02-4200-2 (2 MPPT)",
        mppt_min_v=80.0,
        mppt_max_v=550.0,
        vdc_max=600.0,
        imax_mppt=11.0,
        iscmax_mppt=13.8,
        n_mppt=2
    ),
}

PRESET_MODULES: Dict[str, Module] = {
    "era450": Module(
        name="ERA 450 W 24 V",
        wp=450.0,
        vmp=41.5,
        imp=10.85,
        voc=49.3,
        isc=11.60,
        gamma_pmax_pct_per_C=-0.352,
        beta_voc_pct_per_C=-0.271,
        alpha_isc_pct_per_C=0.049
    ),
}

# ---------------- Core functions ----------------
def energy_daily_from_monthly_kwh(kwh_month: float, days_per_month: float = 30.0) -> float:
    return (kwh_month * 1000.0) / days_per_month

def required_pv_power_wp(E_daily_Wh: float, HSP: float, PR: float) -> float:
    if HSP <= 0 or PR <= 0:
        return math.nan
    return E_daily_Wh / (HSP * PR)

def temp_adjust(value_stc: float, coeff_pct_per_C: float, delta_T: float) -> float:
    return value_stc * (1.0 + (coeff_pct_per_C / 100.0) * delta_T)

def module_at_temps(mod: Module, T_cell_hot: float, T_amb_cold: float) -> Dict[str, float]:
    delta_hot = T_cell_hot - 25.0
    delta_cold = T_amb_cold - 25.0
    vmp_hot = temp_adjust(mod.vmp, mod.gamma_pmax_pct_per_C, delta_hot)
    voc_cold = temp_adjust(mod.voc, mod.beta_voc_pct_per_C, delta_cold)
    isc_cold = temp_adjust(mod.isc, mod.alpha_isc_pct_per_C, delta_cold)
    return dict(vmp_hot=vmp_hot, voc_cold=voc_cold, isc_cold=isc_cold)

def check_string(n_series: int, n_parallel: int, mod: Module, inv: Inverter,
                 T_cell_hot: float, T_amb_cold: float) -> Dict[str, Any]:
    temps = module_at_temps(mod, T_cell_hot, T_amb_cold)
    vmp_hot_str = n_series * temps["vmp_hot"]
    voc_cold_str = n_series * temps["voc_cold"]
    imp_str = mod.imp
    isc_cold_str = n_parallel * temps["isc_cold"]
    imp_total = n_parallel * imp_str

    checks = {
        "mppt_min_ok": vmp_hot_str >= inv.mppt_min_v,
        "mppt_max_ok": vmp_hot_str <= inv.mppt_max_v if inv.mppt_max_v > 0 else True,
        "vdc_max_ok": voc_cold_str <= inv.vdc_max,
        "imax_ok": imp_total <= inv.imax_mppt,
        "iscmax_ok": isc_cold_str <= inv.iscmax_mppt,
    }
    ok = all(checks.values())

    return {
        "n_series": n_series,
        "n_parallel": n_parallel,
        "vmp_hot_string_V": vmp_hot_str,
        "voc_cold_string_V": voc_cold_str,
        "imp_string_A": imp_str,
        "isc_cold_total_A": isc_cold_str,
        "imp_total_A": imp_total,
        "checks": checks,
        "is_compatible": ok,
        "temps": temps,
    }

def estimate_production_kwh_day(total_wp: float, HSP: float, PR: float) -> float:
    return (total_wp / 1000.0) * HSP * PR

def suggest_min_series_for_mppt(mod: Module, inv: Inverter, T_cell_hot: float, max_series: int = 20) -> Optional[int]:
    temps = module_at_temps(mod, T_cell_hot, 25.0)
    for n in range(1, max_series + 1):
        if n * temps["vmp_hot"] >= inv.mppt_min_v:
            return n
    return None

def format_checks(checks: Dict[str, bool]) -> str:
    mapping = {
        "mppt_min_ok": "Vmp_hot ≥ Vmppt_min",
        "mppt_max_ok": "Vmp_hot ≤ Vmppt_max",
        "vdc_max_ok": "Voc_cold ≤ Vdc_max",
        "imax_ok": "I_total ≤ Imax_MPPT",
        "iscmax_ok": "Isc_total ≤ Iscmax_MPPT",
    }
    lines = []
    for k, label in mapping.items():
        status = "OK" if checks.get(k, False) else "FALLA"
        lines.append(f"  - {label}: {status}")
    return "\n".join(lines)

# ---------------- CLI ----------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pv_calc_cli",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
        Calculadora FV on-grid (consola)

        Ejemplos rápidos:
          # Presets AEG + ERA, 3S1P (1 string en 1 MPPT)
          pv_calc_cli.py --preset-inverter aeg4200 --preset-module era450 --kwh-month 115 --hsp 4 --pr 0.8 --t-amb-min 8 --t-cell-hot 65 --series 3 --parallel 1

          # Igual pero 4S1P
          pv_calc_cli.py --preset-inverter aeg4200 --preset-module era450 --kwh-month 115 --hsp 4 --pr 0.8 --t-amb-min 8 --t-cell-hot 65 --series 4

          # Sugerir automáticamente el # en serie mínimo para activar MPPT a calor
          pv_calc_cli.py --preset-inverter aeg4200 --preset-module era450 --kwh-month 115 --hsp 4 --pr 0.8 --t-amb-min 8 --t-cell-hot 65 --auto-series
        """)
    )

    sysg = p.add_argument_group("Sistema")
    sysg.add_argument("--kwh-month", type=float, default=115.0, help="Consumo mensual [kWh/mes]")
    sysg.add_argument("--wh-day", type=float, default=None, help="Consumo diario [Wh/día] (si se indica, tiene prioridad sobre kWh/mes)")
    sysg.add_argument("--hsp", type=float, default=4.0, help="Horas sol pico [h/día]")
    sysg.add_argument("--pr", type=float, default=0.80, help="Performance ratio [0-1]")
    sysg.add_argument("--t-amb-min", type=float, default=8.0, help="Temperatura ambiente mínima [°C] para Voc frío")
    sysg.add_argument("--t-cell-hot", type=float, default=65.0, help="Temperatura de celda caliente [°C] para Vmp caliente")
    sysg.add_argument("--mppts-used", type=int, default=1, help="MPPTs usados simultáneamente (cada uno con su propio string)")

    invg = p.add_argument_group("Inversor")
    invg.add_argument("--preset-inverter", choices=sorted(PRESET_INVERTERS.keys()), help="Usar inversor predefinido")
    invg.add_argument("--inv-name", type=str, help="Nombre inversor")
    invg.add_argument("--inv-mppt-min", type=float, help="MPPT min [V]")
    invg.add_argument("--inv-mppt-max", type=float, help="MPPT max [V]")
    invg.add_argument("--inv-vdc-max", type=float, help="Vdc máximo [V]")
    invg.add_argument("--inv-imax", type=float, help="Corriente máx por MPPT [A]")
    invg.add_argument("--inv-iscmax", type=float, help="Isc máx por MPPT [A]")
    invg.add_argument("--inv-n-mppt", type=int, help="Número de MPPTs")

    modg = p.add_argument_group("Módulo FV")
    modg.add_argument("--preset-module", choices=sorted(PRESET_MODULES.keys()), help="Usar módulo predefinido")
    modg.add_argument("--mod-name", type=str, help="Nombre del módulo")
    modg.add_argument("--mod-wp", type=float, help="Wp [W]")
    modg.add_argument("--mod-vmp", type=float, help="Vmp [V]")
    modg.add_argument("--mod-imp", type=float, help="Imp [A]")
    modg.add_argument("--mod-voc", type=float, help="Voc [V]")
    modg.add_argument("--mod-isc", type=float, help="Isc [A]")
    modg.add_argument("--mod-gamma", type=float, help="γ Pmax [%/°C] (negativo)")
    modg.add_argument("--mod-beta", type=float, help="β Voc [%/°C] (negativo)")
    modg.add_argument("--mod-alpha", type=float, help="α Isc [%/°C] (positivo)")

    strg = p.add_argument_group("String")
    strg.add_argument("--series", type=int, help="Módulos en serie por string (S)")
    strg.add_argument("--parallel", type=int, default=1, help="Strings en paralelo por MPPT (P)")
    strg.add_argument("--auto-series", action="store_true", help="Calcular automáticamente el mínimo S para superar MPPT_min a calor")

    return p

def resolve_inverter(args: argparse.Namespace) -> Inverter:
    if args.preset_inverter:
        inv = PRESET_INVERTERS[args.preset_inverter]
    else:
        inv = Inverter(
            name=args.inv_name or "Inverter (custom)",
            mppt_min_v=args.inv_mppt_min or 80.0,
            mppt_max_v=args.inv_mppt_max or 550.0,
            vdc_max=args.inv_vdc_max or 600.0,
            imax_mppt=args.inv_imax or 11.0,
            iscmax_mppt=args.inv_iscmax or 13.8,
            n_mppt=args.inv_n_mppt or 1
        )
    return inv

def resolve_module(args: argparse.Namespace) -> Module:
    if args.preset_module:
        mod = PRESET_MODULES[args.preset_module]
    else:
        # Require vital fields if no preset
        missing = []
        for field in ("mod_wp", "mod_vmp", "mod_imp", "mod_voc", "mod_isc"):
            if getattr(args, field) is None:
                missing.append(field.replace("mod_", ""))
        if missing:
            sys.exit("Faltan parámetros de módulo (usa --preset-module o define: " + ", ".join(missing) + ")")
        mod = Module(
            name=args.mod_name or "Module (custom)",
            wp=args.mod_wp,
            vmp=args.mod_vmp,
            imp=args.mod_imp,
            voc=args.mod_voc,
            isc=args.mod_isc,
            gamma_pmax_pct_per_C=args.mod_gamma if args.mod_gamma is not None else -0.35,
            beta_voc_pct_per_C=args.mod_beta if args.mod_beta is not None else -0.27,
            alpha_isc_pct_per_C=args.mod_alpha if args.mod_alpha is not None else 0.05
        )
    return mod

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    inv = resolve_inverter(args)
    mod = resolve_module(args)

    # Energy
    if args.wh_day is not None:
        E_daily_Wh = args.wh_day
    else:
        E_daily_Wh = energy_daily_from_monthly_kwh(args.kwh_month, 30.0)
    P_req_wp = required_pv_power_wp(E_daily_Wh, args.hsp, args.pr)

    # Determine series
    if args.auto_series:
        n_series = suggest_min_series_for_mppt(mod, inv, args.t_cell_hot)
        if n_series is None:
            sys.exit("No se encontró # en serie que alcance Vmppt_min con los límites dados.")
    else:
        if args.series is None:
            sys.exit("Debes indicar --series N o usar --auto-series")
        n_series = args.series

    n_parallel = max(1, args.parallel)
    mppts_used = max(1, args.mppts_used)

    # Checks for one MPPT (n_parallel strings en paralelo dentro del mismo MPPT)
    res = check_string(n_series, n_parallel, mod, inv, args.t_cell_hot, args.t_amb_min)

    # Energy production:
    # Caso 1: paralelizar dentro del mismo MPPT (n_parallel>1)
    # Caso 2: usar más de 1 MPPT con un string cada uno (mppts_used>1)
    total_strings = n_parallel * mppts_used
    total_wp = n_series * mod.wp * total_strings
    prod_day = estimate_production_kwh_day(total_wp, args.hsp, args.pr)

    # -------- Report --------
    print("=== CALCULADORA FV ON-GRID (CLI) ===\n")
    print(f"Objetivo: {args.kwh_month:.1f} kWh/mes  ->  {E_daily_Wh:.0f} Wh/día")
    print(f"HSP={args.hsp:.2f} h  PR={args.pr:.2f}  ->  Potencia FV requerida ~ {P_req_wp/1000:.2f} kWp\n")

    print(f"Inversor: {inv.name}")
    print(f"  MPPT: {inv.mppt_min_v:.0f}–{inv.mppt_max_v:.0f} V | Vdc_max: {inv.vdc_max:.0f} V")
    print(f"  Imax_MPPT: {inv.imax_mppt:.2f} A | Iscmax_MPPT: {inv.iscmax_mppt:.2f} A | MPPTs: {inv.n_mppt}\n")

    print(f"Módulo: {mod.name}")
    print(f"  STC: {mod.wp:.0f} Wp  Vmp={mod.vmp:.2f} V  Imp={mod.imp:.2f} A  Voc={mod.voc:.2f} V  Isc={mod.isc:.2f} A")
    print(f"  Coef: γ(Pmax)={mod.gamma_pmax_pct_per_C}%/°C  β(Voc)={mod.beta_voc_pct_per_C}%/°C  α(Isc)={mod.alpha_isc_pct_per_C}%/°C\n")

    temps = module_at_temps(mod, args.t_cell_hot, args.t_amb_min)
    print(f"Supuestos térmicos: T_cell_hot={args.t_cell_hot:.0f} °C, T_amb_min={args.t_amb_min:.0f} °C")
    print(f"  Vmp_hot(mód): {temps['vmp_hot']:.2f} V  |  Voc_cold(mód): {temps['voc_cold']:.2f} V  |  Isc_cold(mód): {temps['isc_cold']:.2f} A\n")

    print(f"--- Configuración evaluada ---")
    print(f"  # en serie (S): {n_series}    |  Strings en paralelo por MPPT (P): {n_parallel}")
    print(f"  MPPTs usados: {mppts_used}    |  Strings totales: {total_strings}")
    print(f"  Vmp_hot(string): {res['vmp_hot_string_V']:.1f} V  |  Voc_cold(string): {res['voc_cold_string_V']:.1f} V")
    print(f"  I_operación(string): {res['imp_string_A']:.2f} A  |  Isc_total_cold (por MPPT): {res['isc_cold_total_A']:.2f} A")
    print("  Comprobaciones:")
    print(format_checks(res["checks"]))
    print(f"\nPotencia pico total: {total_wp/1000:.2f} kWp")
    print(f"Producción estimada: {prod_day:.2f} kWh/d  (~{prod_day*30:.0f} kWh/mes)")

if __name__ == "__main__":
    main()
