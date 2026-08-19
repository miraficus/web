import urllib.request
import re
import json
import xml.etree.ElementTree as ET
import sys

TSV_URL = "https://raw.githubusercontent.com/1jtp8sobiu/ps5-pkg/master/PS5_XML.tsv"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

def parse_system_ver(system_ver_str):
    """Převede desítkové číslo Sony na formátovaný FW (např. 100794368 -> 06.02)"""
    try:
        val = int(system_ver_str)
        hex_val = f"{val:08x}"  # Převod na 8-místný hex
        major = int(hex_val[0:2], 16)
        minor = int(hex_val[2:4], 16)
        return f"{major:02d}.{minor:02d}", float(f"{major}.{minor}")
    except Exception as e:
        return None, None

def fetch_xml_sys_ver(url):
    """Stáhne XML a pokusí se vytáhnout system_ver"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=5) as response:
        xml_text = response.read().decode('utf-8', errors='ignore')
        
        # 1. Pokus přes ElementTree
        try:
            root = ET.fromstring(xml_text)
            for pkg in root.findall('.//package'):
                if 'system_ver' in pkg.attrib:
                    return pkg.attrib['system_ver']
        except Exception:
            pass

        # 2. Záložní pokus přes Regex
        match = re.search(r'system_ver=["\'](\d+)["\']', xml_text)
        if match:
            return match.group(1)

    return None

def main():
    print("Stahuji TSV soubor...")
    req = urllib.request.Request(TSV_URL, headers=HEADERS)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            lines = response.read().decode('utf-8').splitlines()
    except Exception as e:
        print(f"Kritická chyba při stahování TSV: {e}")
        sys.exit(1)

    games_dict = {}
    print(f"Celkem řádků v TSV: {len(lines)}")
    print("Zpracovávám položky...")

    # Přeskočíme hlavičku TSV
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) < 2:
            continue
            
        content_id, title_name = parts[0].strip(), parts[1].strip()
        version_url = parts[2].strip() if len(parts) > 2 else ""
        
        # Extrakce PPSA ID z content_id
        ppsa_match = re.search(r'(PPSA\d{5})', content_id)
        if not ppsa_match:
            continue
            
        ppsa = ppsa_match.group(1)
        
        # Pokud již PPSA v seznamu máme, přeskočíme
        if ppsa in games_dict:
            continue

        # Výchozí hodnoty, pokud by XML selhalo nebo neexistovalo
        fw_display = "Neznámá"
        min_fw_float = 0.0  # Zobrazí se při jakémkoliv zvoleném FW

        # Pokus o zjištění verze z XML (pokud URL existuje)
        if version_url.startswith('http'):
            try:
                sys_ver_raw = fetch_xml_sys_ver(version_url)
                if sys_ver_raw:
                    formatted_str, formatted_float = parse_system_ver(sys_ver_raw)
                    if formatted_str:
                        fw_display = formatted_str
                        min_fw_float = formatted_float
            except Exception as e:
                # Při chybě stahování XML nepadáme, pouze ponecháme výchozí "Neznámá"
                pass

        # Hra se ULOŽÍ VŽDY
        games_dict[ppsa] = {
            "platform": "PS5",
            "ppsa": ppsa,
            "title": title_name,
            "minFw": min_fw_float,
            "fwDisplay": fw_display
        }
        print(f"Uloženo: {ppsa} | {title_name} | FW: {fw_display}")

    # Převod na seznam a seřazení podle názvu
    games_list = list(games_dict.values())
    games_list.sort(key=lambda x: x['title'])

    # Uložení do souboru ps5gamelist.json
    output_path = "ps5gamelist.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(games_list, f, ensure_ascii=False, indent=2)

    print("--------------------------------------------------")
    print(f"HOTOVO! Vygenerováno celkem {len(games_list)} her do {output_path}.")

if __name__ == "__main__":
    main()
