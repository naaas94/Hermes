import os
import random
import pandas as pd
from faker import Faker
from datasets import load_dataset
from fpdf import FPDF

def generate_synthetic_excel():
    print("Generating synthetic Excel dataset for extraction testing...")
    fake = Faker('es_MX')
    
    # We want fields matching VehicleRecord:
    # marca, descripcion, modelo, numero_serie, tipo_vehiculo, cobertura, suma_asegurada, deducible
    
    num_rows = 1500 # A fairly large number to test chunking/streaming
    
    marcas = ["Nissan", "Chevrolet", "Volkswagen", "Kia", "Ford", "Toyota", "Honda", "Mazda"]
    tipos = ["Sedan", "SUV", "Pick-up", "Camioneta", "Hatchback"]
    coberturas = ["Amplia", "Limitada", "Responsabilidad Civil"]
    deducibles = ["5%", "10%", "3%", "15%"]
    
    data = []
    
    for _ in range(num_rows):
        marca = random.choice(marcas)
        modelo = random.randint(2010, 2024)
        tipo = random.choice(tipos)
        descripcion = f"{marca} {tipo} {modelo}"
        
        # Sometimes add noise/nulls
        if random.random() < 0.05:
            marca = None
        
        row = {
            "Marca Vehiculo": marca,
            "Desc. Detallada": descripcion,
            "Año Modelo": modelo if random.random() < 0.95 else None,
            "VIN (Num Serie)": fake.vin() if random.random() < 0.95 else None,
            "Tipo": tipo,
            "Tipo de Cobertura": random.choice(coberturas),
            "Suma Asegurada ($)": round(random.uniform(100000, 800000), 2),
            "Deducible Aplicable": random.choice(deducibles)
        }
        data.append(row)
        
    df = pd.DataFrame(data)
    
    out_path = "test_excel_accuracy_synthetic.xlsx"
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, startrow=3)
        worksheet = writer.sheets['Sheet1']
        worksheet['A1'] = "REPORTE DE FLOTILLA - SEGUROS MONTERREY"
        worksheet['A2'] = "CLIENTE: GRUPO BIMBO S.A. DE C.V."
        worksheet['A3'] = "Póliza: 9988-1122"
        
    print(f"Generated {out_path} with {num_rows} rows.")

def generate_riscbac_pdf():
    print("Fetching PDF for stress testing...")
    
    # Generate a more realistic PDF using Faker directly instead of relying on the dataset text which seems empty or malformed
    from faker import Faker
    import random
    
    fake = Faker()
    out_path = "test_pdf_stress_riscbac.pdf"
    
    class PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 14)
            self.cell(0, 10, "Commercial Motor Vehicle Insurance Policy", new_x="LMARGIN", new_y="NEXT", align="C")
            self.set_font("Helvetica", "", 10)
            self.cell(0, 10, "Schedule & Certificate of Insurance", new_x="LMARGIN", new_y="NEXT", align="C")
            self.line(10, 30, 200, 30)
            self.ln(10)
            
        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.cell(0, 10, f"Page {self.page_no()}", new_x="RIGHT", new_y="TOP", align="C")

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Generate 15 pages of complex policy text to test chunking
    for page in range(15):
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        
        if page == 0:
            # Page 1: Policy Details (High density of entities)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, "Insured Details", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            
            # Use pseudo-table format
            details = [
                f"Policy Number: POL-{fake.bothify(text='??-####-####')}",
                f"Period of Insurance: {fake.date_between(start_date='-1y', end_date='today')} to {fake.date_between(start_date='today', end_date='+1y')}",
                f"Insured Name: {fake.company()}",
                f"Address: {fake.address().replace(chr(10), ', ')}",
                f"Business/Profession: Logistics & Transport"
            ]
            
            for detail in details:
                pdf.cell(80, 8, detail, new_x="LMARGIN", new_y="NEXT")
                
            pdf.ln(10)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, "Vehicle Schedule", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            
            # Generate 5 vehicles on page 1
            for i in range(5):
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 8, f"Vehicle #{i+1}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 10)
                
                v_details = f"Registration: {fake.bothify(text='??##??####')} | Make/Model: {random.choice(['Tata', 'Ashok Leyland', 'Mahindra'])} {fake.word().capitalize()} | Year: {random.randint(2015, 2023)} | Engine No: {fake.bothify(text='ENG########')} | Chassis No: {fake.bothify(text='CHS########')} | IDV: Rs. {random.randint(500000, 2500000)}.00"
                pdf.multi_cell(0, 6, v_details)
                pdf.ln(5)
                
        else:
            # Other pages: Terms, Conditions, Clauses (Test context window and chunking)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, f"Policy Terms & Conditions - Section {page}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            
            for _ in range(8):
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 8, f"Clause {page}.{random.randint(1, 100)} - {fake.catch_phrase()}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 10)
                pdf.multi_cell(0, 6, fake.text(max_nb_chars=800))
                pdf.ln(5)
                
            # Randomly sprinkle another vehicle record to test extraction across chunks
            if random.random() > 0.5:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 8, "Endorsement - Additional Vehicle", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 10)
                v_details = f"Registration: {fake.bothify(text='??##??####')} | Make/Model: {random.choice(['Volvo', 'Eicher', 'BharatBenz'])} {fake.word().capitalize()} | Year: {random.randint(2015, 2023)} | Engine No: {fake.bothify(text='ENG########')} | Chassis No: {fake.bothify(text='CHS########')} | IDV: Rs. {random.randint(500000, 2500000)}.00"
                pdf.multi_cell(0, 6, v_details)

    pdf.output(out_path)
    print(f"Generated {out_path} from synthetic data. File size: {os.path.getsize(out_path)} bytes.")

if __name__ == "__main__":
    generate_synthetic_excel()
    try:
        generate_riscbac_pdf()
    except Exception as e:
        print("Failed to generate RISCBAC PDF:", e)
