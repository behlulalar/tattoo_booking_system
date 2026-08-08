#!/usr/bin/env python3
"""
COPY komutlarını INSERT komutlarına çevirir
pgAdmin için uyumlu SQL dosyası oluşturur
"""

import re

def escape_sql_value(value):
    """SQL değerini escape et"""
    if value == '' or value == '\\N':
        return 'NULL'
    elif value == 't':
        return 'TRUE'
    elif value == 'f':
        return 'FALSE'
    else:
        # String değerleri escape et
        val_escaped = value.replace("'", "''").replace('\\', '\\\\')
        return f"'{val_escaped}'"

def convert_copy_to_insert(content):
    """COPY komutlarını INSERT komutlarına çevir"""
    lines = content.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # COPY komutunu bul
        if line.startswith('COPY ') and 'FROM stdin;' in line:
            # Tablo adını ve kolonları çıkar
            match = re.match(r'COPY public\.(\w+) \((.+)\) FROM stdin;', line)
            if match:
                table_name = match.group(1)
                columns = match.group(2)
                
                result.append('-- Data for Name: ' + table_name)
                result.append('')
                
                i += 1
                # Veri satırlarını oku
                data_lines = []
                while i < len(lines) and lines[i] != '\\.':
                    if lines[i].strip() and not lines[i].startswith('--'):
                        data_lines.append(lines[i])
                    i += 1
                
                # INSERT komutlarına çevir
                for data_line in data_lines:
                    if data_line.strip():
                        values = data_line.strip().split('\t')
                        # Değerleri temizle ve SQL formatına çevir
                        formatted_values = []
                        for val in values:
                            formatted_values.append(escape_sql_value(val))
                        
                        values_str = ', '.join(formatted_values)
                        insert_stmt = f'INSERT INTO public.{table_name} ({columns}) VALUES ({values_str});'
                        result.append(insert_stmt)
                
                result.append('')
                result.append('')
                if i < len(lines) and lines[i] == '\\.':
                    i += 1
                    continue
        
        result.append(line)
        i += 1
    
    return '\n'.join(result)

if __name__ == '__main__':
    input_file = 'dump_2025-12-31_19-05-57.sql'
    output_file = 'dump_2025-12-31_19-05-57_pgadmin.sql'
    
    print(f"📖 Dosya okunuyor: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("🔄 COPY komutları INSERT komutlarına çevriliyor...")
    converted = convert_copy_to_insert(content)
    
    print(f"💾 Yeni dosya yazılıyor: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(converted)
    
    print("✅ Dönüştürme tamamlandı!")
    print(f"📄 pgAdmin için hazır dosya: {output_file}")

