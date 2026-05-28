import os
import sys
import pandas as pd
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from core.report_generator import (
    generate_branded_chart,
    compile_pdf,
    compile_docx,
    compile_pptx,
    compile_xlsx
)

def run_tests():
    print("[START] Starting Report Generation E2E Tests...")
    
    # Load test sales csv
    csv_path = Path(__file__).parent.parent / "test_sales.csv"
    if not csv_path.exists():
        print(f"[ERROR] {csv_path} does not exist.")
        sys.exit(1)
        
    df = pd.read_csv(csv_path)
    print(f"[DATA] Loaded dataframe with {len(df)} rows and columns: {list(df.columns)}")
    
    # Define outputs directory inside scratch
    scratch_dir = Path(__file__).parent
    outputs_dir = scratch_dir / "test_outputs"
    outputs_dir.mkdir(exist_ok=True)
    
    chart_path = outputs_dir / "temp_test_chart.png"
    pdf_path = outputs_dir / "test_report.pdf"
    docx_path = outputs_dir / "test_report.docx"
    pptx_path = outputs_dir / "test_report.pptx"
    xlsx_path = outputs_dir / "test_report.xlsx"
    
    brand_colors = {"primary": "#10b981", "secondary": "#34d399"} # Emerald Mint theme
    kpis = [
        {"title": "Total Revenue Calculated", "metric": "$173,150", "severity": "success"},
        {"title": "Total Sales Volume", "metric": "3,483 Units", "severity": "info"},
        {"title": "Missing Parameter Warning", "metric": "0 Null values", "severity": "warning"}
    ]
    
    narrative_text = (
        "## Executive Performance Overview\n\n"
        "Business operations in the current period have progressed with significant milestones achieved in product distribution. "
        "Sales grew consistently month over month, driven primarily by strong demand in the Widget B segment within the South region.\n\n"
        "## Key Performance Outlines\n\n"
        "Total sales volume exceeded our targets, proving that regional marketing expansions were highly effective. "
        "No data completeness warnings were identified, validating the schema's high transactional integrity."
    )
    
    # 1. Test Chart Generation
    print("\n[Test 1] Generating branded OOP Matplotlib chart...")
    chart_ok = generate_branded_chart(
        df=df,
        x_col="month",
        y_col="revenue",
        chart_type="line",
        colors=brand_colors,
        save_path=str(chart_path)
    )
    assert chart_ok, "Chart generation failed"
    assert chart_path.exists(), "Chart file was not created"
    assert chart_path.stat().st_size > 0, "Chart file is empty"
    print("[SUCCESS] Chart generated successfully and verified.")
    
    # 2. Test PDF Compilation
    print("\n[Test 2] Compiling branded PDF report...")
    compile_pdf(
        filepath=str(pdf_path),
        title="Widget Sales & Revenue Report",
        date_range="Jan 2024 - Jun 2024",
        narrative=narrative_text,
        kpis=kpis,
        chart_path=str(chart_path),
        brand_colors=brand_colors
    )
    assert pdf_path.exists(), "PDF report was not created"
    assert pdf_path.stat().st_size > 0, "PDF file is empty"
    print("[SUCCESS] PDF compiled successfully and verified.")
    
    # 3. Test DOCX Compilation
    print("\n[Test 3] Compiling branded DOCX report...")
    compile_docx(
        filepath=str(docx_path),
        title="Widget Sales & Revenue Report",
        date_range="Jan 2024 - Jun 2024",
        narrative=narrative_text,
        kpis=kpis,
        chart_path=str(chart_path),
        brand_colors=brand_colors
    )
    assert docx_path.exists(), "DOCX report was not created"
    assert docx_path.stat().st_size > 0, "DOCX file is empty"
    print("[SUCCESS] DOCX compiled successfully and verified.")
    
    # 4. Test PPTX Compilation
    print("\n[Test 4] Compiling branded PPTX presentation...")
    compile_pptx(
        filepath=str(pptx_path),
        title="Widget Sales & Revenue Report",
        date_range="Jan 2024 - Jun 2024",
        narrative=narrative_text,
        kpis=kpis,
        chart_path=str(chart_path),
        brand_colors=brand_colors
    )
    assert pptx_path.exists(), "PPTX presentation was not created"
    assert pptx_path.stat().st_size > 0, "PPTX file is empty"
    print("[SUCCESS] PPTX compiled successfully and verified.")
    
    # 5. Test XLSX Compilation
    print("\n[Test 5] Compiling branded XLSX dataset spreadsheet...")
    compile_xlsx(
        filepath=str(xlsx_path),
        title="Widget Sales & Revenue Report",
        df=df,
        brand_colors=brand_colors
    )
    assert xlsx_path.exists(), "XLSX dataset was not created"
    assert xlsx_path.stat().st_size > 0, "XLSX file is empty"
    print("[SUCCESS] XLSX compiled successfully and verified.")
    
    # Clean up generated files
    print("\n[CLEANUP] Cleaning up test outputs...")
    for file in [chart_path, pdf_path, docx_path, pptx_path, xlsx_path]:
        if file.exists():
            file.unlink()
    outputs_dir.rmdir()
    print("[SUCCESS] Cleanup complete.")
    
    print("\n[COMPLETE] All E2E Report Export compiler tests passed successfully!")

if __name__ == "__main__":
    run_tests()
