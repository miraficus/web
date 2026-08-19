import urllib.request
import urllib.error
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
        print(f"   [!] Chyba při převodu čísla system_ver '{system_ver_str}': {e}")
        return None, None

def fetch_xml_sys_ver(url):
    """Stáhne XML a pokusí se vytáhnout system_ver + loguje podrobnosti"""
    req = urllib.request.Request(url, headers=HEADERS)
    
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_text = response.read().decode('utf-8', errors='ignore')
            
            if not xml_text.strip():
                print(f"   [!] XML odpoveď byla prázdná.")
                return None

            # 1. Pokus přes ElementTree
            try:
                root = ET.fromstring(xml_text)
                for pkg in root.findall('.//package'):
                    if 'system_ver' in pkg.attrib:
                        return pkg.attrib['system_ver']
                print(f"   [!] Element <package> s atributem system_ver nebyl v XML nalezen.")
            except Exception as xml_err:
                print(f"   [!] ElementTree selhal při parsování XML: {xml_err}")

            # 2. Záložní pokus přes Regex
            match = re.search(r'system_ver=["\'](\d+)["\']', xml_text)
            if match:
                print(f"   [i] Našel se system_ver pomocí Regexu!")
                return match.group(1)
            else:
                print(f"   [!] Regex nenašel 'system_ver' v textu XML.")

    except urllib.error.HTTPError as e:
        print(f"   [!] HTTP Chyba {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        print(f"   [!] URL Chyba (spojení selhalo): {e.reason}")
    except Exception as e:
        print(f"   [!] Neočekávaná chyba při stahování XML: {e}")

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
    print("Zpracovávám položky...\n" + "="*50)

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

        print(f"\nZpracovávám: {ppsa} | {title_name}")
        print(f"   URL z TSV: '{version_url}'")

        fw_display = "Neznámá"
        min_fw_float = 0.0

        if version_url.startswith('http'):
            sys_ver_raw = fetch_xml_sys_ver(version_url)
            if sys_ver_raw:
                formatted_str, formatted_float = parse_system_ver(sys_ver_raw)
                if formatted_str:
                    fw_display = formatted_str
                    min_fw_float = formatted_float
                    print(f"   [SUCCESS] FW Nalezen: {fw_display}")
        else:
            print(f"   [!] Neplatná URL adresa (nezačíná na http).")

        games_dict[ppsa] = {
            "platform": "PS5",
            "ppsa": ppsa,
            "title": title_name,
            "minFw": min_fw_float,
            "fwDisplay": fw_display
        }

    games_list = list(games_dict.values())
    games_list.sort(key=lambda x: x['title'])

    output_path = "ps5gamelist.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(games_list, f, ensure_ascii=False, indent=2)

    print("\n" + "="*50)
    print(f"HOTOVO! Vygenerováno celkem {len(games_list)} her do {output_path}.")

if __name__ == "__main__":
    main()
