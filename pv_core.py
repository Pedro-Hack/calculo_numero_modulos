# pv_core.py
from dataclasses import dataclass, asdict
from typing import Dict, Any
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
    max_system_v: float
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
        "vdc_max_ok": voc_cold_str <= min(inv.vdc_max, mod.max_system_v),
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

def suggest_series_range(mod: Module, inv: Inverter, T_cell_hot: float, T_amb_cold: float) -> Dict[str, float]:
    temps = module_at_temps(mod, T_cell_hot, T_amb_cold)
    vmp_hot_mod = temps["vmp_hot"]
    voc_cold_mod = temps["voc_cold"]
    min_series = math.ceil(inv.mppt_min_v / vmp_hot_mod) if vmp_hot_mod > 0 else 1
    vlimit = min(inv.vdc_max, mod.max_system_v)
    max_series_vlimit = math.floor(vlimit / voc_cold_mod) if voc_cold_mod > 0 else 999
    max_series_mppt = math.floor(inv.mppt_max_v / vmp_hot_mod) if inv.mppt_max_v > 0 and vmp_hot_mod > 0 else 999
    max_series = min(max_series_vlimit, max_series_mppt)
    return {
        "min_series": max(min_series, 1),
        "max_series_vlimit": max_series_vlimit,
        "vlimit_used": vlimit,
        "max_series_mppt": max_series_mppt,
        "max_series": max_series,
        "vmp_hot_mod": vmp_hot_mod,
        "voc_cold_mod": voc_cold_mod
    }

def plan_distribution(required_strings: int, n_mppt: int, max_parallel_per_mppt: int):
    dist = [0]*n_mppt
    remain = max(0, required_strings)
    for i in range(n_mppt):
        if remain <= 0: break
        dist[i] = min(1, remain)
        remain -= dist[i]
    level = 2
    while remain > 0 and level <= max_parallel_per_mppt:
        for i in range(n_mppt):
            if remain <= 0: break
            if dist[i] < level and dist[i] < max_parallel_per_mppt:
                dist[i] += 1
                remain -= 1
        level += 1
    return dist, remain

def format_checks_labels() -> Dict[str, str]:
    return {
        "mppt_min_ok": "Vmp_hot(string) ≥ Vmppt_min (calor)",
        "mppt_max_ok": "Vmp_hot(string) ≤ Vmppt_max (calor)",
        "vdc_max_ok": "Voc_cold(string) ≤ min(Vdc_max inv, Vsys_max mod) (frío)",
        "imax_ok": "I_operación_total ≤ Imax_MPPT",
        "iscmax_ok": "Isc_total_cold ≤ Iscmax_MPPT (frío)",
    }

def compute_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    kwh_month = float(payload.get("kwh_month") or 0) if payload.get("kwh_month") not in ("", None) else 0.0
    wh_day = float(payload.get("wh_day") or 0) if payload.get("wh_day") not in ("", None) else 0.0
    days = float(payload.get("days") or 30.0)
    HSP = float(payload.get("HSP") or 4.0)
    PR = float(payload.get("PR") or 0.8)
    T_amb_min = float(payload.get("T_amb_min") or 8.0)
    T_cell_hot = float(payload.get("T_cell_hot") or 65.0)

    if wh_day > 0:
        E_daily_Wh = wh_day
        kwh_month_calc = E_daily_Wh * days / 1000.0
    else:
        kwh_month_calc = kwh_month
        E_daily_Wh = energy_daily_from_monthly_kwh(kwh_month_calc, days)

    inv = Inverter(
        name=payload.get("inv_name") or "Custom Inverter",
        mppt_min_v=float(payload.get("mppt_min") or 80.0),
        mppt_max_v=float(payload.get("mppt_max") or 550.0),
        vdc_max=float(payload.get("vdc_max") or 600.0),
        imax_mppt=float(payload.get("imax") or 11.0),
        iscmax_mppt=float(payload.get("iscmax") or 13.8),
        n_mppt=int(payload.get("n_mppt") or 2),
    )

    mod = Module(
        name=payload.get("mod_name") or "Custom Module",
        wp=float(payload.get("wp") or 450.0),
        vmp=float(payload.get("vmp") or 41.5),
        imp=float(payload.get("imp") or 10.85),
        voc=float(payload.get("voc") or 49.3),
        isc=float(payload.get("isc") or 11.6),
        max_system_v=float(payload.get("max_sys_v") or 1000.0),
        gamma_pmax_pct_per_C=float(payload.get("gamma") or -0.35),
        beta_voc_pct_per_C=float(payload.get("beta") or -0.27),
        alpha_isc_pct_per_C=float(payload.get("alpha") or 0.05),
    )

    auto_series = payload.get("auto_series") in ("on", True, "true", "1", 1)
    n_series = int(payload.get("n_series") or 3)
    n_parallel = int(payload.get("n_parallel") or 1)
    mppts_used = int(payload.get("mppts_used") or 1)

    P_req_wp = required_pv_power_wp(E_daily_Wh, HSP, PR)
    rng = suggest_series_range(mod, inv, T_cell_hot, T_amb_min)
    if auto_series:
        n_series = int(rng["min_series"])

    res_mppt = check_string(n_series, n_parallel, mod, inv, T_cell_hot, T_amb_min)

    total_strings = n_parallel * mppts_used
    total_wp = n_series * mod.wp * total_strings
    prod_day = estimate_production_kwh_day(total_wp, HSP, PR)
    prod_month = prod_day * 30.0

    need_kwh_day = E_daily_Wh / 1000.0
    cobertura_pct = (prod_day / need_kwh_day * 100.0) if need_kwh_day > 0 else 100.0

    recos = {}
    if prod_day + 1e-9 < need_kwh_day:
        deficit_kwh_day = need_kwh_day - prod_day
        temps_cold = module_at_temps(mod, T_cell_hot, T_amb_min)
        isc_cold_mod = temps_cold['isc_cold']
        allowed_by_imp = int(math.floor(inv.imax_mppt / mod.imp)) if mod.imp > 0 else 0
        allowed_by_isc = int(math.floor(inv.iscmax_mppt / isc_cold_mod)) if isc_cold_mod > 0 else 0
        max_parallel_per_mppt = max(0, min(allowed_by_imp, allowed_by_isc))

        required_strings = int(math.ceil(P_req_wp / max(1e-9, (n_series*mod.wp))))
        strings_totales_actual = total_strings
        strings_adicionales_necesarios = max(0, required_strings - strings_totales_actual)

        target_dist, leftover = plan_distribution(required_strings, inv.n_mppt, max_parallel_per_mppt)
        total_wp_target = n_series * mod.wp * sum(target_dist)
        prod_day_target = estimate_production_kwh_day(total_wp_target, HSP, PR)

        recos = {
            "deficit_kwh_day": deficit_kwh_day,
            "deficit_kwh_month": deficit_kwh_day*30.0,
            "strings_req": required_strings,
            "strings_actual": strings_totales_actual,
            "strings_extra_needed": strings_adicionales_necesarios,
            "max_parallel_per_mppt": max_parallel_per_mppt,
            "capacity_total_strings": inv.n_mppt * max_parallel_per_mppt,
            "target_dist": target_dist,
            "leftover": leftover,
            "prod_day_target": prod_day_target,
            "total_wp_target": total_wp_target,
        }

    return {
        "inputs": {
            "kwh_month": kwh_month_calc,
            "wh_day": E_daily_Wh,
            "days": days,
            "HSP": HSP,
            "PR": PR,
            "T_amb_min": T_amb_min,
            "T_cell_hot": T_cell_hot,
            "auto_series": auto_series,
            "n_series": n_series,
            "n_parallel": n_parallel,
            "mppts_used": mppts_used,
            "inverter": asdict(inv),
            "module": asdict(mod),
        },
        "ranges": rng,
        "string_check": res_mppt,
        "P_req_wp": P_req_wp,
        "total": {
            "strings": total_strings,
            "wp": total_wp,
            "prod_day": prod_day,
            "prod_month": prod_month,
            "coverage_pct": cobertura_pct,
        },
        "recos": recos,
        "labels": format_checks_labels(),
    }
