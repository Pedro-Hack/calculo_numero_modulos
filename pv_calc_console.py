#!/usr/bin/env python3
from dataclasses import dataclass
from typing import Optional, Dict, Any
import math

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

def format_checks(checks):
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

def main():
    # --- User-editable inputs ---
    kwh_month = 115.0
    HSP = 4.0
    PR = 0.80
    T_amb_min = 8.0
    T_cell_hot = 65.0

    inv = Inverter(
        name="AEG AS-IR02-4200-2 (2 MPPT)",
        mppt_min_v=80.0,
        mppt_max_v=550.0,
        vdc_max=600.0,
        imax_mppt=11.0,
        iscmax_mppt=13.8,
        n_mppt=2
    )

    mod = Module(
        name="ERA 450 W 24 V",
        wp=450.0,
        vmp=41.5,
        imp=10.85,
        voc=49.3,
        isc=11.60,
        gamma_pmax_pct_per_C=-0.352,
        beta_voc_pct_per_C=-0.271,
        alpha_isc_pct_per_C=0.049
    )

    E_daily_Wh = energy_daily_from_monthly_kwh(kwh_month, days_per_month=30.0)
    P_req_wp = required_pv_power_wp(E_daily_Wh, HSP, PR)

    print("=== CALCULADORA FV ON-GRID (CONSOLA) ===\\n")
    print(f"Objetivo: {kwh_month:.1f} kWh/mes  ->  {E_daily_Wh:.0f} Wh/día")
    print(f"HSP={HSP:.2f} h  PR={PR:.2f}  ->  Potencia FV requerida ~ {P_req_wp/1000:.2f} kWp\\n")

    print(f"Inversor: {inv.name}")
    print(f"  MPPT: {inv.mppt_min_v:.0f}–{inv.mppt_max_v:.0f} V | Vdc_max: {inv.vdc_max:.0f} V")
    print(f"  Imax_MPPT: {inv.imax_mppt:.2f} A | Iscmax_MPPT: {inv.iscmax_mppt:.2f} A | MPPTs: {inv.n_mppt}\\n")

    print(f"Módulo: {mod.name}")
    print(f"  STC: {mod.wp:.0f} Wp  Vmp={mod.vmp:.2f} V  Imp={mod.imp:.2f} A  Voc={mod.voc:.2f} V  Isc={mod.isc:.2f} A")
    print(f"  Coef: γ(Pmax)={mod.gamma_pmax_pct_per_C}%/°C  β(Voc)={mod.beta_voc_pct_per_C}%/°C  α(Isc)={mod.alpha_isc_pct_per_C}%/°C\\n")

    print(f"Supuestos térmicos: T_cell_hot={T_cell_hot:.0f} °C, T_amb_min={T_amb_min:.0f} °C")
    temps = module_at_temps(mod, T_cell_hot, T_amb_min)
    print(f"  Vmp_hot(mód): {temps['vmp_hot']:.2f} V  |  Voc_cold(mód): {temps['voc_cold']:.2f} V  |  Isc_cold(mód): {temps['isc_cold']:.2f} A\\n")

    n_series_min = suggest_min_series_for_mppt(mod, inv, T_cell_hot)
    if n_series_min is not None:
        print(f"Mínimo #módulos en serie para superar Vmppt_min a calor: {n_series_min}S\\n")

    for n_series in (3, 4):
        res = check_string(n_series, n_parallel=1, mod=mod, inv=inv,
                           T_cell_hot=T_cell_hot, T_amb_cold=T_amb_min)
        total_wp = n_series * mod.wp
        prod = estimate_production_kwh_day(total_wp, HSP, PR)
        print(f"--- Configuración propuesta: {n_series}S1P (un string en 1 MPPT) ---")
        print(f"  Potencia pico: {total_wp/1000:.2f} kWp")
        print(f"  Vmp_hot(string): {res['vmp_hot_string_V']:.1f} V  |  Voc_cold(string): {res['voc_cold_string_V']:.1f} V")
        print(f"  I_operación(string): {res['imp_string_A']:.2f} A  |  Isc_total_cold(hasta cortocir.): {res['isc_cold_total_A']:.2f} A")
        print("  Comprobaciones:")
        print(format_checks(res['checks']))
        print(f"  Producción estimada: {prod:.2f} kWh/d  (~{prod*30:.0f} kWh/mes)\\n")

    total_wp_future = 2 * 3 * mod.wp
    prod_future = estimate_production_kwh_day(total_wp_future, HSP, PR)
    print("--- Ampliación futura sugerida ---")
    print("  2 strings independientes (cada uno en su MPPT): 3S1P + 3S1P")
    print(f"  Potencia pico: {total_wp_future/1000:.2f} kWp | Producción: {prod_future:.2f} kWh/d (~{prod_future*30:.0f} kWh/mes)")

if __name__ == "__main__":
    main()
