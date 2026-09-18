import os
from datetime import datetime

from consar.config import HISTORICAL_DB
from consar.reports.modules import cartera as cartera_section
from consar.reports.modules.data import AforeDataLoader
from consar.reports.modules.calculator import AUMCalculator
from consar.reports.modules.charts import ChartGenerator
from consar.reports.modules.pdf import AforePDFReport
from consar.reports.modules.summary import SummaryGenerator


def format_currency(value, currency):
    if currency == 'USD':
        return f"${value:,.2f}M"
    return f"${value:,.0f}M"

def format_percent(value):
    return f"{value:,.1f}%"

def main():
    # 1. Load Data from the historical DB (set via config or MASTER_DB_PATH env var)
    if not os.path.exists(HISTORICAL_DB):
        print(f"Error: Database not found at {HISTORICAL_DB}")
        return

    print(f"Loading data from {HISTORICAL_DB}")
    loader = AforeDataLoader(HISTORICAL_DB).load()
    calculator = AUMCalculator(loader)

    # Get latest period
    year, month = loader.get_latest_period()
    print(f"Generating reports for {year}-{month}...")

    # Concepts to analyze
    concepts = [
        {'key': 'mandatos', 'name': 'Third Party Mandates'},
        {'key': 'mutual_funds', 'name': 'Mutual Funds'},
        {'key': 'active_management', 'name': 'Active Management (Mandates + Mutual Funds)'}
    ]

    # Pre-calculate all metrics for summary generation
    print("Pre-calculating metrics for summary...")
    all_metrics = {}
    total_assets_metrics = {}

    for currency in ['MXN', 'USD']:
        all_metrics[currency] = {}

        # Calculate total assets
        total_assets_metrics[currency] = calculator.get_all_growth_metrics(
            year, month, 'total_assets', include_active_management=False
        )

        for concept in concepts:
            key = concept['key']
            include_active = (key == 'active_management')
            calc_key = 'mandatos' if include_active else key

            metrics = calculator.get_all_growth_metrics(
                year, month, calc_key, include_active_management=include_active
            )
            all_metrics[currency][key] = metrics

    # Generate Reports
    currencies = ['MXN', 'USD']
    for currency in currencies:
        print(f"Creating {currency} report...")
        pdf = AforePDFReport(f"Afore Investment Analysis - {currency}", currency)

        # --- EXECUTIVE SUMMARY ---
        pdf.set_header_title(f"Executive Summary - {currency}")
        pdf.chapter_title("Executive Summary")

        summary_text = SummaryGenerator.generate_executive_dashboard_text(
            all_metrics[currency], currency
        )
        if summary_text:
            pdf.chapter_body(summary_text)
            pdf.ln(5)

        # Add Active/Fund Summary Table
        pdf.chapter_title("Fund Assets Overview (AUM & Growth)")

        # Calculate individual growth for last 3 months
        monthly_stats = []

        for i in range(3):
            y, m = calculator.calculate_period_offset(year, month, i)
            y_prev, m_prev = calculator.calculate_period_offset(year, month, i + 1)

            m_name = datetime(int(y), int(m), 1).strftime('%b %y')

            start_data = calculator.aggregate_by_afore(y_prev, m_prev, 'mutual_funds')
            end_data = calculator.aggregate_by_afore(y, m, 'mutual_funds')
            growth = calculator.calculate_growth(start_data, end_data, currency)

            monthly_stats.append((m_name, growth))

        headers, rows = SummaryGenerator.generate_active_fund_summary_table(
            all_metrics[currency],
            monthly_stats,
            currency
        )
        pdf.add_table(headers, rows, col_widths=[35, 27, 36, 36, 36])
        pdf.ln(5)

        # Add Total AUM Table
        pdf.chapter_title("Total AUM by Afore")
        headers, rows = SummaryGenerator.generate_total_aum_table(
            total_assets_metrics[currency],
            currency
        )
        pdf.add_table(headers, rows, col_widths=[60, 60, 40])
        pdf.ln(5)

        # --- SYSTEM PORTFOLIO COMPOSITION (CONSAR SISET md=18) ---
        # Read-only: whatever `cartera --update` last wrote. Skipped with a note
        # when the file is missing or lags the report period, so a stale cartera
        # never blocks the AUM report.
        composition, skip_reason = cartera_section.load_composition(
            report_period=f"{year}-{month}"
        )
        if composition:
            # Title before add_page: header() draws with whatever is set at the
            # time the page is created.
            pdf.set_header_title(f"System Portfolio Composition - {currency}")
            pdf.add_page()
            pdf.chapter_title("System Portfolio Composition")
            pdf.chapter_body(
                f"Share of SIEFORE net assets by asset class, {composition['period']}. "
                "Source: CONSAR SISET (md=18), monthly series since January 2019. "
                "MoM and YoY are changes in percentage points."
            )
            pdf.ln(3)

            warning = cartera_section.integrity_note(composition)
            if warning:
                pdf.chapter_body(warning)
                pdf.ln(3)

            market_total = next(
                (row for row in total_assets_metrics[currency]['ytd'][currency]
                 if row['afore'] == "MARKET TOTAL"),
                None
            )
            headers, rows = cartera_section.build_table(
                composition,
                currency,
                total_aum_millions=market_total['end_value'] if market_total else None
            )
            pdf.add_table(headers, rows, col_widths=[62, 30, 24, 24, 34])
            pdf.ln(5)
        else:
            print(f"   Skipping portfolio composition section: {skip_reason}")

        for concept in concepts:
            key = concept['key']
            name = concept['name']

            metrics = all_metrics[currency][key]

            header_title = f"{name} Analysis - {currency}"
            pdf.set_header_title(header_title)

            pdf.add_page()
            pdf.chapter_title(f"{name} Overview")

            # --- CHART GENERATION ---
            ytd_data = metrics['ytd'][currency]
            chart_path = f"output/chart_{key}_{currency}_ytd.png"
            os.makedirs("output", exist_ok=True)

            ChartGenerator.create_growth_bar_chart(
                ytd_data,
                title=f"{name} - YTD Growth ({currency})",
                show_percentage=True,
                output_path=chart_path
            )
            pdf.add_image(chart_path)

            # --- GROWTH TABLE ---
            pdf.chapter_title(f"{name} Growth Analysis")

            header = ["Afore", "Total AUM", "YTD Growth", "YTD %", "1Y Growth", "1Y %", "3Y Growth", "3Y %"]
            col_widths = [30, 25, 22, 18, 22, 18, 22, 18]

            table_data = []

            def get_afore_data(data_list, afore_name):
                for item in data_list:
                    if item['afore'] == afore_name:
                        return item
                return None

            raw_afores = [d for d in ytd_data if d['afore'] != "MARKET TOTAL"]
            raw_afores.sort(key=lambda x: x['afore'])
            market_total = [d for d in ytd_data if d['afore'] == "MARKET TOTAL"][0]

            sorted_ytd = raw_afores + [market_total]

            for d_ytd in sorted_ytd:
                afore = d_ytd['afore']
                row = [afore]

                row.append(format_currency(d_ytd['end_value'], currency))

                row.append(format_currency(d_ytd['growth_absolute'], currency))
                row.append(format_percent(d_ytd['growth_percent']))

                d_1y = get_afore_data(metrics['1_year'].get(currency, []), afore)
                if d_1y:
                    row.append(format_currency(d_1y['growth_absolute'], currency))
                    row.append(format_percent(d_1y['growth_percent']))
                else:
                    row.extend(["-", "-"])

                d_3y = get_afore_data(metrics['3_year'].get(currency, []), afore)
                if d_3y:
                    row.append(format_currency(d_3y['growth_absolute'], currency))
                    row.append(format_percent(d_3y['growth_percent']))
                else:
                    row.extend(["-", "-"])

                table_data.append(row)

            pdf.add_table(header, table_data, col_widths=col_widths)

        # Save Report
        filename = f"output/Afore_Report_{year}_{month}_{currency}.pdf"
        pdf.output(filename)
        print(f"Report saved to {filename}")

    # Clean up charts
    ChartGenerator.close_all()

if __name__ == "__main__":
    main()
