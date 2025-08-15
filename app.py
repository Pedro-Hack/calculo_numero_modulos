from flask import Flask, request, render_template_string

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Cálculo de Módulos en Serie (Voc)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root{--bg:#0b1220;--card:#111a2b;--muted:#8aa0c6;--text:#e7eefc;--accent:#5aa3ff;--ok:#2ecc71;--warn:#f1c40f;--bad:#e74c3c;}
  body{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Ubuntu; background:linear-gradient(180deg,#0b1220 0%, #0e1628 100%); color:var(--text);}
  .wrap{max-width:880px;margin:40px auto;padding:0 16px;}
  .card{background:var(--card);border:1px solid #1e2a44;border-radius:18px;box-shadow:0 10px 30px rgba(0,0,0,.35);overflow:hidden}
  .header{padding:20px 24px;border-bottom:1px solid #1e2a44;display:flex;justify-content:space-between;align-items:center}
  .header h1{margin:0;font-size:20px;letter-spacing:.3px}
  .content{padding:20px 24px;display:grid;grid-template-columns:1fr 1fr;gap:20px}
  .field{display:flex;flex-direction:column;gap:8px}
  label{font-size:13px;color:var(--muted)}
  input{background:#0b1324;border:1px solid #203154;border-radius:12px;padding:12px 14px;color:var(--text);font-size:15px;outline:none}
  input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(90,163,255,.15)}
  .actions{padding:0 24px 20px}
  button{background:var(--accent);color:white;border:none;border-radius:12px;padding:12px 18px;font-weight:600;cursor:pointer}
  .results{padding:20px 24px;border-top:1px solid #1e2a44;display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
  .metric{background:#0b1324;border:1px solid #203154;border-radius:14px;padding:14px}
  .metric h3{margin:0 0 6px 0;font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.2px}
  .metric p{margin:0;font-size:20px;font-weight:700}
  .badge{display:inline-block;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700}
  .ok{background:rgba(46,204,113,.15);color:var(--ok);border:1px solid rgba(46,204,113,.4)}
  .warn{background:rgba(241,196,15,.12);color:var(--warn);border:1px solid rgba(241,196,15,.4)}
  .bad{background:rgba(231,76,60,.12);color:var(--bad);border:1px solid rgba(231,76,60,.4)}
  .note{padding:0 24px 24px;color:var(--muted);font-size:13px}
  @media (max-width:900px){
    .content{grid-template-columns:1fr}
    .results{grid-template-columns:1fr 1fr}
  }
</style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="header">
        <h1>Cálculo del número máximo de módulos en serie (Voc)</h1>
        <span class="badge ok">PV Tool</span>
      </div>

      <form method="post">
        <div class="content">
          <div class="field">
            <label for="Voc_modulo">Voc del módulo (V)</label>
            <input id="Voc_modulo" name="Voc_modulo" type="number" step="0.01" min="0" required value="{{ form_vals.Voc_modulo }}">
          </div>
          <div class="field">
            <label for="coef_temp">Coeficiente temperatura del Voc (1/°C, ej: -0.003)</label>
            <input id="coef_temp" name="coef_temp" type="number" step="0.0001" required value="{{ form_vals.coef_temp }}">
          </div>
          <div class="field">
            <label for="temp_min">Temperatura mínima esperada (°C)</label>
            <input id="temp_min" name="temp_min" type="number" step="0.1" required value="{{ form_vals.temp_min }}">
          </div>
          <div class="field">
            <label for="voltaje_max">Voltaje máximo del inversor (V)</label>
            <input id="voltaje_max" name="voltaje_max" type="number" step="0.1" min="0" required value="{{ form_vals.voltaje_max }}">
          </div>
        </div>

        <div class="actions">
          <button type="submit">Calcular</button>
        </div>
      </form>

      {% if show_results %}
      <div class="results">
        <div class="metric">
          <h3>Nº máximo de módulos en serie</h3>
          <p>{{ n_max }}</p>
        </div>
        <div class="metric">
          <h3>Voc total (a {{ temp_min }} °C)</h3>
          <p>{{ voc_total }} V</p>
        </div>
        <div class="metric">
          <h3>Voc por módulo (a {{ temp_min }} °C)</h3>
          <p>{{ voc_modulo_res }} V</p>
        </div>
        <div class="metric">
          <h3>Uso del límite del inversor</h3>
          <p>
            {{ uso_pct }}%
            {% if uso_class == 'ok' %}
              <span class="badge ok">Cómodo</span>
            {% elif uso_class == 'warn' %}
              <span class="badge warn">Ajustado</span>
            {% else %}
              <span class="badge bad">Excede</span>
            {% endif %}
          </p>
        </div>
      </div>
      <div class="note">
        Tip: si el uso está por encima de ~95%, considera reducir 1 módulo o aplicar un margen de seguridad.
      </div>
      {% endif %}
    </div>
  </div>
</body>
</html>
"""

def calcular_n_max(voc_modulo, coef_temp, temp_min, vmax_inv, cap=100):
    delta_T = temp_min - 25.0
    n_max = 0
    for n in range(1, cap + 1):
        voc_total = voc_modulo * n * (1 + coef_temp * delta_T)
        if voc_total <= vmax_inv:
            n_max = n
        else:
            break
    return n_max, delta_T

@app.route("/", methods=["GET", "POST"])
def main():
    form_vals = {
        "Voc_modulo": "45.6",
        "coef_temp": "-0.003",
        "temp_min": "0",
        "voltaje_max": "600"
    }
    show_results = False
    n_max = voc_total = voc_modulo_res = uso_pct = None
    uso_class = "ok"
    temp_min = form_vals["temp_min"]

    if request.method == "POST":
        Voc_modulo = float(request.form["Voc_modulo"])
        coef_temp = float(request.form["coef_temp"])
        temp_min = float(request.form["temp_min"])
        voltaje_max = float(request.form["voltaje_max"])

        form_vals = {
            "Voc_modulo": request.form["Voc_modulo"],
            "coef_temp": request.form["coef_temp"],
            "temp_min": request.form["temp_min"],
            "voltaje_max": request.form["voltaje_max"],
        }

        n_max, dT = calcular_n_max(Voc_modulo, coef_temp, temp_min, voltaje_max, cap=100)
        voc_modulo_res_val = Voc_modulo * (1 + coef_temp * dT)
        voc_total_val = voc_modulo_res_val * n_max

        # Métricas redondeadas
        voc_modulo_res = f"{voc_modulo_res_val:.2f}"
        voc_total = f"{voc_total_val:.2f}"

        # Uso del límite
        uso_pct_val = (voc_total_val / voltaje_max) * 100 if voltaje_max > 0 else 0
        uso_pct = f"{uso_pct_val:.1f}"

        # Clasificación
        if uso_pct_val < 90:
            uso_class = "ok"
        elif uso_pct_val <= 100:
            uso_class = "warn"
        else:
            uso_class = "bad"

        show_results = True

    return render_template_string(
        HTML,
        form_vals=form_vals,
        show_results=show_results,
        n_max=n_max,
        voc_total=voc_total,
        voc_modulo_res=voc_modulo_res,
        uso_pct=uso_pct,
        uso_class=uso_class,
        temp_min=temp_min
    )

if __name__ == "__main__":
    app.run(debug=True)
