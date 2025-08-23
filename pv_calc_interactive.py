#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calculadora FV on-grid (interactiva por consola)

Permite ingresar:
- Consumo (kWh/mes o Wh/día), HSP, PR, temperaturas (frío/calor)
- Parámetros del inversor (hasta 8 MPPT, límites de tensión y corrientes)
- Parámetros del módulo (Wp, Vmp, Imp, Voc, Isc y coeficientes térmicos, Máx. tensión de sistema 1000/1500 V)
- Topología del arreglo: # en serie (S), # de strings en paralelo por MPPT (P), # de MPPT usados

Entrega:
- kWp requeridos para el objetivo
- Rango S permitido por tensiones (mín S por MPPT_min a calor, máx S por min(Vdc_max inv, Vsys_max módulo) y por MPPT_max)
- Chequeos eléctricos (tensión/corriente)
- Producción estimada diaria y mensual
- Recomendaciones automáticas si la producción NO cubre la demanda
- Plan automático de distribución de strings por MPPT
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math

# --------- Modelos ---------
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

# --------- Utilidades ---------
def to_float(s: str) -> float:
    s = s.strip().replace(",", ".")
    return float(s)

def ask_float(prompt: str, default: Optional[float] = None, minv: Optional[float] = None, maxv: Optional[float] = None) -> float:
    while True:
        txt = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not txt and default is not None:
            val = float(default)
        else:
            try:
                val = to_float(txt or "nan")
            except Exception:
                print("  -> Valor inválido, intenta de nuevo.")
                continue
        if (minv is not None and val < minv) or (maxv is not None and val > maxv):
            print(f"  -> Debe estar entre {minv} y {maxv}.")
            continue
        return val

def ask_int(prompt: str, default: Optional[int] = None, minv: Optional[int] = None, maxv: Optional[int] = None) -> int:
    while True:
        txt = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not txt and default is not None:
            val = int(default)
        else:
            try:
                val = int(to_float(txt))
            except Exception:
                print("  -> Valor inválido, intenta de nuevo.")
                continue
        if (minv is not None and val < minv) or (maxv is not None and val > maxv):
            print(f"  -> Debe estar entre {minv} y {maxv}.")
            continue
        return val

def ask_yesno(prompt: str, default: bool = False) -> bool:
    suf = " [S/n]" if default else " [s/N]"
    while True:
        txt = input(prompt + suf + ": ").strip().lower()
        if txt == "" and default is not None:
            return default
        if txt in ("s", "si", "sí", "y", "yes"):
            return True
        if txt in ("n", "no"):
            return False
        print("  -> Responde con s/n.")

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

def suggest_series_range(mod: Module, inv: Inverter, T_cell_hot: float, T_amb_cold: float) -> Dict[str, int]:
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
        "max_series": max_series
    }

def format_checks(checks: Dict[str, bool]) -> str:
    mapping = {
        "mppt_min_ok": "Vmp_hot ≥ Vmppt_min",
        "mppt_max_ok": "Vmp_hot ≤ Vmppt_max",
        "vdc_max_ok": "Voc_cold ≤ min(Vdc_max inv, Vsys_max mod)",
        "imax_ok": "I_total ≤ Imax_MPPT",
        "iscmax_ok": "Isc_total ≤ Iscmax_MPPT",
    }
    lines = []
    for k, label in mapping.items():
        status = "OK" if checks.get(k, False) else "FALLA"
        lines.append(f"  - {label}: {status}")
    return "\n".join(lines)

def plan_distribution(required_strings: int, n_mppt: int, max_parallel_per_mppt: int):
    """
    Devuelve una lista con la cantidad de strings por MPPT (longitud n_mppt)
    priorizando: 1) usar MPPT libres con 1 string cada uno, 2) luego paralelizar
    de forma balanceada hasta max_parallel_per_mppt.
    """
    dist = [0]*n_mppt
    remain = max(0, required_strings)
    # Primer pase: 1 string por MPPT
    for i in range(n_mppt):
        if remain <= 0: break
        dist[i] = min(1, remain)
        remain -= dist[i]
    # Siguientes pases: añadir paralelos por rondas
    level = 2
    while remain > 0 and level <= max_parallel_per_mppt:
        for i in range(n_mppt):
            if remain <= 0: break
            if dist[i] < level and dist[i] < max_parallel_per_mppt:
                dist[i] += 1
                remain -= 1
        level += 1
    return dist, remain  # remain>0 => no alcanzó capacidad

# --------- Flujo interactivo ---------
def main():
    print("=== CALCULADORA FV ON-GRID (INTERACTIVA) ===\n")

    # --- Sistema ---
    if ask_yesno("¿Ingresar consumo en Wh/día directamente?", default=False):
        E_daily_Wh = ask_float("Wh/día", 3833, 1)
        kwh_month = E_daily_Wh * 30.0 / 1000.0
    else:
        kwh_month = ask_float("Consumo mensual objetivo [kWh/mes]", 115.0, 0.1)
        dias = ask_float("Días por mes para el cálculo", 30.0, 1)
        E_daily_Wh = energy_daily_from_monthly_kwh(kwh_month, dias)

    HSP = ask_float("HSP [h/día]", 4.0, 0.1)
    PR = ask_float("PR [0-1]", 0.80, 0.1, 1.0)
    T_amb_min = ask_float("Temperatura ambiente mínima [°C]", 8.0, -50, 60)
    T_cell_hot = ask_float("Temperatura de celda caliente [°C]", 65.0, 25, 90)

    # --- Inversor ---
    print("\n--- Datos del inversor ---")
    inv_name = input("Nombre del inversor [Custom Inverter]: ").strip() or "Custom Inverter"
    n_mppt = ask_int("Cantidad de MPPT (1-8)", 2, 1, 8)
    mppt_min = ask_float("MPPT min [V]", 80.0, 10)
    mppt_max = ask_float("MPPT max [V]", 550.0, mppt_min)
    vdc_max = ask_float("Vdc máxima [V]", 600.0, mppt_max)
    imax = ask_float("Corriente máx por MPPT [A]", 11.0, 1)
    iscmax = ask_float("Isc máx por MPPT [A]", 13.8, 1)

    inv = Inverter(inv_name, mppt_min, mppt_max, vdc_max, imax, iscmax, n_mppt)

    # --- Módulo ---
    print("\n--- Datos del módulo FV ---")
    mod_name = input("Nombre del módulo [Custom Module]: ").strip() or "Custom Module"
    wp = ask_float("Wp del módulo [W]", 450.0, 1)
    vmp = ask_float("Vmp [V]", 41.5, 5)
    imp = ask_float("Imp [A]", 10.85, 1)
    voc = ask_float("Voc [V]", 49.3, 5)
    isc = ask_float("Isc [A]", 11.60, 1)
    max_sys_v = ask_float("Tensión máxima del sistema (módulo) [V] (p.ej. 1000 o 1500)", 1000.0, 600, 2000)
    gamma = ask_float("γ Pmax [%/°C] (negativo)", -0.35, -2, 0)
    beta = ask_float("β Voc [%/°C] (negativo)", -0.27, -2, 0)
    alpha = ask_float("α Isc [%/°C] (positivo)", 0.05, 0, 1)

    mod = Module(mod_name, wp, vmp, imp, voc, isc, max_sys_v, gamma, beta, alpha)

    # --- Topología del arreglo ---
    print("\n--- Topología del arreglo ---")
    if ask_yesno("¿Calcular automáticamente el # en serie mínimo para activar el MPPT en calor?", default=True):
        rng = suggest_series_range(mod, inv, T_cell_hot, T_amb_min)
        n_series = rng["min_series"]
        print(f"  -> Serie mínimo sugerido (calor): {n_series}S (rango permitido: {rng['min_series']}S ... {rng['max_series']}S)")
    else:
        n_series = ask_int("Módulos en serie (S)", 3, 1)

    n_parallel = ask_int("Strings en paralelo por MPPT (P)", 1, 1)
    mppts_used = ask_int("MPPTs usados (cada uno con un string)", 1, 1, n_mppt)

    # --- Cálculos ---
    P_req_wp = required_pv_power_wp(E_daily_Wh, HSP, PR)

    # Rango seguro de serie
    rng = suggest_series_range(mod, inv, T_cell_hot, T_amb_min)

    # Chequeo por MPPT (paralelos en el mismo MPPT)
    res_mppt = check_string(n_series, n_parallel, mod, inv, T_cell_hot, T_amb_min)

    # Producción con MPPTs usados (cada uno con un string).
    total_strings = n_parallel * mppts_used
    total_wp = n_series * mod.wp * total_strings
    prod_day = estimate_production_kwh_day(total_wp, HSP, PR)
    prod_month = prod_day * 30.0

    # --- Reporte ---
    print("\n================= REPORTE =================")
    print(f"Objetivo: {kwh_month:.2f} kWh/mes  ->  {E_daily_Wh:.0f} Wh/día")
    print(f"HSP={HSP:.2f} h  PR={PR:.2f}  ->  Potencia FV requerida ≈ {P_req_wp/1000:.2f} kWp")
    print("\nInversor: ", inv.name)
    print(f"  MPPT: {inv.mppt_min_v:.0f}–{inv.mppt_max_v:.0f} V  |  Vdc_max: {inv.vdc_max:.0f} V")
    print(f"  Imax_MPPT: {inv.imax_mppt:.2f} A  |  Iscmax_MPPT: {inv.iscmax_mppt:.2f} A  |  MPPTs: {inv.n_mppt}")
    print("\nMódulo: ", mod.name)
    print(f"  STC: {mod.wp:.0f} Wp  Vmp={mod.vmp:.2f} V  Imp={mod.imp:.2f} A  Voc={mod.voc:.2f} V  Isc={mod.isc:.2f} A  |  Vsys_max(mod)={mod.max_system_v:.0f} V")
    temps = module_at_temps(mod, T_cell_hot, T_amb_min)
    print(f"  Coef: γ={mod.gamma_pmax_pct_per_C}%/°C  β={mod.beta_voc_pct_per_C}%/°C  α={mod.alpha_isc_pct_per_C}%/°C")
    print(f"  Térmico: Vmp_hot(mód)={temps['vmp_hot']:.2f} V  |  Voc_cold(mód)={temps['voc_cold']:.2f} V  |  Isc_cold(mód)={temps['isc_cold']:.2f} A")
    print("\n--- Serie permitida por tensiones ---")
    print(f"  Serie mínima (calor) por MPPT_min: {rng['min_series']}S")
    print(f"  Límite de tensión usado (min entre Vdc_max inversor y Vsys_max módulo): {rng['vlimit_used']:.0f} V")
    print(f"  Serie máxima por límite de tensión: {rng['max_series_vlimit']}S  |  por MPPT_max: {rng['max_series_mppt']}S  =>  Máx permitido: {rng['max_series']}S")

    print("\n--- Configuración evaluada ---")
    print(f"  # en serie (S): {n_series}  |  Strings en paralelo por MPPT (P): {n_parallel}")
    print(f"  MPPTs usados: {mppts_used}  |  Strings totales: {total_strings}")
    print(f"  Vmp_hot(string): {res_mppt['vmp_hot_string_V']:.1f} V  |  Voc_cold(string): {res_mppt['voc_cold_string_V']:.1f} V")
    print(f"  I_operación(string): {res_mppt['imp_string_A']:.2f} A  |  Isc_total_cold (por MPPT): {res_mppt['isc_cold_total_A']:.2f} A")
    print("  Comprobaciones:")
    print(format_checks(res_mppt['checks']))

    print("\n--- Producción estimada ---")
    print(f"  Potencia pico total: {total_wp/1000:.2f} kWp")
    print(f"  Producción: {prod_day:.2f} kWh/d  (~{prod_month:.0f} kWh/mes)")

    # --- Recomendaciones si no se cubre la demanda ---
    need_kwh_day = E_daily_Wh / 1000.0
    cobertura_pct = (prod_day / need_kwh_day * 100.0) if need_kwh_day > 0 else 100.0
    print(f"\nCobertura del objetivo: {cobertura_pct:.1f}%")
    if prod_day + 1e-9 < need_kwh_day:
        deficit_kwh_day = need_kwh_day - prod_day
        deficit_kwh_month = deficit_kwh_day * 30.0

        temps_cold = module_at_temps(mod, T_cell_hot, T_amb_min)
        isc_cold_mod = temps_cold['isc_cold']
        allowed_by_imp = int(math.floor(inv.imax_mppt / mod.imp)) if mod.imp > 0 else 0
        allowed_by_isc = int(math.floor(inv.iscmax_mppt / isc_cold_mod)) if isc_cold_mod > 0 else 0
        max_parallel_per_mppt = max(0, min(allowed_by_imp, allowed_by_isc))

        strings_por_string = n_series * mod.wp
        strings_totales_actual = total_strings
        strings_totales_requeridos = int(math.ceil((need_kwh_day*1000.0) / (mod.wp * HSP * PR) / max(1e-9, 1.0)) * (1 if n_series>0 else 1))
        # mejor: usar kWp requerido:
        strings_totales_requeridos = int(math.ceil((required_pv_power_wp(E_daily_Wh, HSP, PR)) / max(1e-9, (n_series*mod.wp))))
        strings_adicionales_necesarios = max(0, strings_totales_requeridos - strings_totales_actual)

        libres_en_mppt_actuales = mppts_used * max(0, max_parallel_per_mppt - n_parallel)
        libres_en_mppt_nuevos = max(0, inv.n_mppt - mppts_used) * max_parallel_per_mppt
        capacidad_strings_extra = libres_en_mppt_actuales + libres_en_mppt_nuevos

        print("\n--- Recomendaciones (déficit detectado) ---")
        print(f"  • Falta aprox.: {deficit_kwh_day:.2f} kWh/d (~{deficit_kwh_month:.0f} kWh/mes)")
        print(f"  • Potencia DC instalada: {total_wp/1000:.2f} kWp  |  Potencia DC requerida: {required_pv_power_wp(E_daily_Wh, HSP, PR)/1000:.2f} kWp")
        print(f"  • Strings actuales: {strings_totales_actual}  |  Strings requeridos: {strings_totales_requeridos}  |  Adicionales: {strings_adicionales_necesarios}")

        if max_parallel_per_mppt == 0:
            print("  • Atención: el módulo excede la corriente permitida por MPPT incluso con 1 string.")
            print("    → Cambia a un inversor con mayor Imax/Isc por MPPT o a un módulo de menor Imp/Isc.")
        else:
            if strings_adicionales_necesarios <= capacidad_strings_extra:
                usar_mppt_libres = min(strings_adicionales_necesarios, max(0, inv.n_mppt - mppts_used))
                restantes = strings_adicionales_necesarios - usar_mppt_libres
                if usar_mppt_libres > 0:
                    print(f"  • Añade {usar_mppt_libres} string(s) en MPPT(s) libre(s) (1 por MPPT).")
                if restantes > 0:
                    print(f"  • Además, aumenta paralelo en MPPT(s) activo(s) hasta P≤{max_parallel_per_mppt} (actual: P={n_parallel}).")
                print("  • Verifica que cada MPPT no supere Imax/Isc con el paralelismo propuesto.")
            else:
                faltan = strings_adicionales_necesarios - capacidad_strings_extra
                print(f"  • Con este inversor no hay entradas DC suficientes: faltarían ~{faltan} string(s) adicionales.")
                print("    Opciones:")
                print("    – Usar módulos de mayor Wp pero igual/baja corriente para subir kWp por string sin violar Imax.")
                print("    – Cambiar a inversor con mayor Imax por MPPT o más MPPTs.")
                print("    – Revisar sombras/PR: si PR es bajo por suciedad/sombras, corrige causas para subir producción.")
        print("  Nota: subir la serie (S) no aumenta energía, solo voltaje. Usa más strings (P o más MPPT) para subir kWp.")

        # Plan automático de distribución final
        if max_parallel_per_mppt > 0 and inv.n_mppt > 0:
            required_strings = int(math.ceil(required_pv_power_wp(E_daily_Wh, HSP, PR) / max(1e-9, (n_series*mod.wp))))
            capacity_total = inv.n_mppt * max_parallel_per_mppt
            target_dist, leftover = plan_distribution(required_strings, inv.n_mppt, max_parallel_per_mppt)

            current_dist = [0]*inv.n_mppt
            for i in range(min(inv.n_mppt, mppts_used)):
                current_dist[i] = n_parallel

            print("\n--- Configuración sugerida ---")
            if leftover > 0:
                print(f"  • El inversor no alcanza el objetivo con módulos actuales: capacidad máx={capacity_total} strings (faltan {leftover}).")
                print("  • Sugerencia: adopta la distribución máxima posible y evalúa aumentar Wp por string o cambiar inversor.")
            total_wp_target = n_series * mod.wp * sum(target_dist)
            prod_day_target = estimate_production_kwh_day(total_wp_target, HSP, PR)
            print(f"  • Objetivo: {required_strings} strings  |  Capacidad inversor: {capacity_total}  |  Plan: {sum(target_dist)} strings")
            print(f"  • Potencia pico plan: {total_wp_target/1000:.2f} kWp  |  Producción estimada: {prod_day_target:.2f} kWh/d (~{prod_day_target*30:.0f} kWh/mes)")
            print("  • Distribución por MPPT (strings):")
            for i, val in enumerate(target_dist, start=1):
                print(f"    - MPPT {i}: {val}")

            add_steps = []
            for i in range(inv.n_mppt):
                delta = max(0, target_dist[i] - current_dist[i])
                if delta > 0:
                    if current_dist[i] == 0 and delta > 0:
                        add_steps.append(f"    - MPPT {i+1}: añadir {delta} string(s) (actualmente vacío)")
                    else:
                        add_steps.append(f"    - MPPT {i+1}: aumentar de {current_dist[i]} → {target_dist[i]} (añadir {delta})")
            if add_steps:
                print("  • Pasos sugeridos para llegar al plan:")
                for s in add_steps:
                    print(s)
            else:
                print("  • Ya estás en una configuración que cumple el objetivo (según este modelo).")
    else:
        print("La producción estimada cubre el objetivo.")

    print("\n==========================================")

if __name__ == "__main__":
    main()
