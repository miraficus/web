import urllib.request
import re
import json
import xml.etree.ElementTree as ET
import sys

TSV_URL = "https://raw.githubusercontent.com/1jtp8sobiu/ps5-pkg/master/PS5_XML.tsv"

def parse_system_ver(system_ver_str):
    """Převede dekadické/hex systémové číslo Sony na formátovaný FW (např. 06.02)"""
    try:
        val = int(system_ver_str)
        hex_val = f"{val:08x}"  # Převod na 8-místný hex řetězec
        major = int(hex_val[0:2], 16)
        minor = int(hex_val[2:4], 16)
        return f"{major:02d}.{minor:02d}"
    except Exception:
        return None

def main():
    print("Stahuji TSV soubor...")
    req = urllib.request.Request(TSV_URL, headers={'User-Agent': 'Mozilla/5.0'})
    
    with urllib.request.urlopen(req) as response:
        lines = response.read().decode('utf-8').splitlines()

    games_dict = {}

    print("Zpracovávám položky a stahuji verze z XML...")
    
    # Přeskočíme hlavičku TSV
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) < 3:
            continue
            
        content_id, title_name, version_url = parts[0], parts[1], parts[2]
        
        # Extrakce PPSA ID z content_id (např. IP9100-PPSA01280_00-... -> PPSA01280)
        ppsa_match = re.search(r'(PPSA\d{5})', content_id)
        if not ppsa_match or not version_url.startswith('http'):
            continue
            
        ppsa = ppsa_match.group(1)
        
        # Pokud již PPSA v seznamu máme, nebudeme XML stahovat znovu
        if ppsa in games_dict:
            continue

        try:
            xml_req = urllib.request.Request(version_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(xml_req, timeout=5) as xml_res:
                xml_data = xml_res.read()
                root = ET.fromstring(xml_data)
                
                # Vyhledání atributu system_ver v tagu package
                package = root.find('.//package')
                if package is not None and 'system_ver' in package.attrib:
                    sys_ver_raw = package.attrib['system_ver']
                    fw_formatted = parse_system_ver(sys_ver_raw)
                    
                    if fw_formatted:
                        games_dict[ppsa] = {
                            "platform": "PS5",
                            "ppsa": ppsa,
                            "title": title_name.strip(),
                            "minFw": float(fw_formatted),
                            "fwDisplay": fw_formatted
                        }
                        print(f"Uloženo: {ppsa} | {title_name} | FW: {fw_formatted}")
        except Exception as e:
            # Pokud se XML nepodaří stáhnout nebo má chybu, přeskočí se
            continue

    # Převod na seznam
    games_list = list(games_dict.values())
    games_list.sort(key=lambda x: x['title'])

    # Uložení do souboru ps5gamelist.json
    output_path = "docs/ps5gamelist.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(games_list, f, ensure_ascii=False, indent=2)

    print(f"Hotovo! Vygenerováno {len(games_list)} her do {output_path}.")

if __name__ == "__main__":
    main()
