# app.py
from flask import Flask, render_template, request, make_response
from pv_core import compute_report
import csv, io, json

app = Flask(__name__)

def defaults():
    return {
        "kwh_month": 115,
        "days": 30,
        "HSP": 4.0,
        "PR": 0.80,
        "T_amb_min": 8.0,
        "T_cell_hot": 65.0,
        "inv_name": "Custom Inverter",
        "n_mppt": 2,
        "mppt_min": 80.0,
        "mppt_max": 550.0,
        "vdc_max": 600.0,
        "imax": 11.0,
        "iscmax": 13.8,
        "mod_name": "Custom Module",
        "wp": 450.0,
        "vmp": 41.5,
        "imp": 10.85,
        "voc": 49.3,
        "isc": 11.60,
        "max_sys_v": 1000.0,
        "gamma": -0.35,
        "beta": -0.27,
        "alpha": 0.05,
        "auto_series": True,
        "n_series": 3,
        "n_parallel": 1,
        "mppts_used": 1,
        "dc_ac_target": 1.20,  # objetivo típico
        "inv_ac_kw": "",       # opcional: potencia AC del inversor
    }

def parse_form(form):
    data = form.to_dict()
    data["auto_series"] = "on" if data.get("auto_series") else ""
    return data

@app.route("/", methods=["GET", "POST"])
def index():
    vals = defaults()
    report = None
    if request.method == "POST":
        data = parse_form(request.form)
        report = compute_report(data)
        vals.update(data)
    return render_template("index.html", vals=vals, report=report)

@app.route("/export/csv", methods=["POST"])
def export_csv():
    report = compute_report(parse_form(request.form))
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["Campo", "Valor"])
    w.writerow(["kWh/mes objetivo", report["inputs"]["kwh_month"]])
    w.writerow(["Wh/día objetivo", report["inputs"]["wh_day"]])
    w.writerow(["HSP", report["inputs"]["HSP"]])
    w.writerow(["PR", report["inputs"]["PR"]])
    w.writerow(["T_amb_min (°C)", report["inputs"]["T_amb_min"]])
    w.writerow(["T_cell_hot (°C)", report["inputs"]["T_cell_hot"]])
    w.writerow(["S (serie)", report["inputs"]["n_series"]])
    w.writerow(["P (paralelo/MPPT)", report["inputs"]["n_parallel"]])
    w.writerow(["MPPTs usados", report["inputs"]["mppts_used"]])
    w.writerow(["Potencia requerida (kWp)", report["P_req_wp"]/1000.0])
    w.writerow(["Potencia instalada (kWp)", report["total"]["wp"]/1000.0])
    w.writerow(["Producción (kWh/d)", report["total"]["prod_day"]])
    w.writerow(["Producción (kWh/mes)", report["total"]["prod_month"]])
    w.writerow(["Cobertura (%)", report["total"]["coverage_pct"]])
    resp = make_response(output.getvalue().encode("utf-8"))
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=report_fv.csv"
    return resp

@app.route("/export/json", methods=["POST"])
def export_json():
    report = compute_report(parse_form(request.form))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    resp = make_response(payload.encode("utf-8"))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=report_fv.json"
    return resp

@app.route("/export/pdf", methods=["POST"])
def export_pdf():
    # Usa xhtml2pdf si está instalado; si falla, devuelve HTML imprimible
    try:
        from xhtml2pdf import pisa
        html = render_template("report_pdf.html", report=compute_report(parse_form(request.form)))
        result = io.BytesIO()
        pisa.CreatePDF(io.StringIO(html), dest=result, encoding='utf-8')
        pdf = result.getvalue()
        resp = make_response(pdf)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = "attachment; filename=report_fv.pdf"
        return resp
    except Exception as e:
        html = render_template("report_pdf.html", report=compute_report(parse_form(request.form)), fallback_error=str(e))
        resp = make_response(html)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=report_fv.html"
        return resp

if __name__ == "__main__":
    app.run(debug=True)
