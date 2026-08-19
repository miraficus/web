import urllib.request
import urllib.error
import re
import json
import xml.etree.ElementTree as ET
import sys
import ssl
import os

TSV_URL = "https://raw.githubusercontent.com/1jtp8sobiu/ps5-pkg/master/PS5_XML.tsv"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

def parse_system_ver(system_ver_str):
    """Převede číslování Sony na reálnou verzi PS5 FW"""
    try:
        val = int(system_ver_str)
        major = (val >> 24) & 0xFF
        minor = (val >> 16) & 0xFF

        if major > 13 or major == 0:
            return "01.00", 1.0

        formatted_str = f"{major:02d}.{minor:02d}"
        formatted_float = float(f"{major}.{minor}")
        return formatted_str, formatted_float
    except Exception:
        return None, None

def fetch_xml_all_versions(url):
    """Projede XML a vrátí seznam všech nalezených verzí FW pro danou hru"""
    req = urllib.request.Request(url, headers=HEADERS)
    raw_versions = []
    
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl_context) as response:
            xml_text = response.read().decode('utf-8', errors='ignore')
            
            if not xml_text.strip():
                return []

            # 1. Hledání všech atributů system_ver v XML přes ElementTree
            try:
                root = ET.fromstring(xml_text)
                for pkg in root.findall('.//package'):
                    if 'system_ver' in pkg.attrib:
                        raw_versions.append(pkg.attrib['system_ver'])
            except Exception:
                pass

            # 2. Záložní Regex pro odchycení všech výskytů
            if not raw_versions:
                matches = re.findall(r'system_ver=["\'](\d+)["\']', xml_text)
                raw_versions.extend(matches)

    except Exception as e:
        print(f"   [!] Chyba při stahování XML: {e}")

    return raw_versions

def main():
    print("Stahuji TSV soubor...")
    req = urllib.request.Request(TSV_URL, headers=HEADERS)
    
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
            lines = response.read().decode('utf-8').splitlines()
    except Exception as e:
        print(f"Kritická chyba při stahování TSV: {e}")
        sys.exit(1)

    games_dict = {}
    print(f"Celkem řádků v TSV: {len(lines)}")
    print("Zpracovávám položky...")

    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) < 2:
            continue
            
        content_id, title_name = parts[0].strip(), parts[1].strip()
        version_url = parts[2].strip() if len(parts) > 2 else ""
        
        ppsa_match = re.search(r'(PPSA\d{5})', content_id)
        if not ppsa_match:
            continue
            
        ppsa = ppsa_match.group(1)
        if ppsa in games_dict:
            continue

        min_fw_float = 0.0
        fw_display = "Neznámá"

        if version_url.startswith('http'):
            raw_vers = fetch_xml_all_versions(version_url)
            parsed_vers = []

            for rv in raw_vers:
                f_str, f_num = parse_system_ver(rv)
                if f_str and f_num:
                    parsed_vers.append((f_num, f_str))

            if parsed_vers:
                # Seřadíme verze od nejnižší po nejvyšší
                parsed_vers.sort(key=lambda x: x[0])
                
                min_fw_float = parsed_vers[0][0]
                min_fw_str = parsed_vers[0][1]
                max_fw_str = parsed_vers[-1][1]

                # Pokud je verze na disku a v patchi stejná, zobrazíme jen jednu
                if min_fw_str == max_fw_str:
                    fw_display = min_fw_str
                else:
                    fw_display = f"{min_fw_str} ➔ {max_fw_str}"

        games_dict[ppsa] = {
            "platform": "PS5",
            "ppsa": ppsa,
            "title": title_name,
            "minFw": min_fw_float,     # Používá se pro filtrování (základní disk)
            "fwDisplay": fw_display
        }

    games_list = list(games_dict.values())
    games_list.sort(key=lambda x: x['title'])

    os.makedirs("docs", exist_ok=True)
    output_path = "docs/ps5gamelist.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(games_list, f, ensure_ascii=False, indent=2)

    print(f"HOTOVO! Vygenerováno {len(games_list)} her do {output_path}.")

if __name__ == "__main__":
    main()
