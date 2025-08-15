# Datos de entrada
Voc_modulo = float(input("Ingrese el Voc nominal del módulo (V): "))
coef_temp = float(input("Ingrese el coeficiente de temperatura del Voc (ej: -0.003): "))
temp_min = float(input("Ingrese la temperatura mínima esperada (°C): "))
voltaje_max_inversor = float(input("Ingrese el voltaje máximo permitido del inversor (V): "))

# Cálculo de ΔT
delta_T = temp_min - 25

# Bucle para encontrar el máximo número de módulos en serie sin superar el límite
N_modulos_max = 0
for N in range(1, 100):  # asumo que nunca pondrás más de 100 módulos en serie
    Voc_total = Voc_modulo * N * (1 + coef_temp * delta_T)
    if Voc_total <= voltaje_max_inversor:
        N_modulos_max = N
    else:
        break

# Resultado
print(f"\nNúmero máximo recomendado de módulos en serie: {N_modulos_max}")
Voc_total_max = Voc_modulo * N_modulos_max * (1 + coef_temp * delta_T)
print(f"Voc total a temperatura mínima ({temp_min}°C): {Voc_total_max:.2f} V")
