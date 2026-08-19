import urllib.request
import urllib.error
import re
import json
import xml.etree.ElementTree as ET
import sys
import ssl
import os
import csv
import io

LOCAL_CSV_PATH = "entitlements_ps5.csv"
GITHUB_TSV_URL = "https://raw.githubusercontent.com/1jtp8sobiu/ps5-pkg/master/PS5_XML.tsv"

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
    """Stáhne XML a vrátí seznam všech nalezených verzí FW pro danou hru"""
    if not url or not url.startswith('http'):
        return []

    req = urllib.request.Request(url, headers=HEADERS)
    raw_versions = []
    
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl_context) as response:
            xml_text = response.read().decode('utf-8', errors='ignore')
            
            if not xml_text.strip():
                return []

            try:
                root = ET.fromstring(xml_text)
                for pkg in root.findall('.//package'):
                    if 'system_ver' in pkg.attrib:
                        raw_versions.append(pkg.attrib['system_ver'])
            except Exception:
                pass

            if not raw_versions:
                matches = re.findall(r'system_ver=["\'](\d+)["\']', xml_text)
                raw_versions.extend(matches)

    except Exception:
        pass

    return raw_versions

def is_dlc_or_addon(entitlement_id, title_name):
    """Přísná detekce DLC/doplňků podle entitlement_id i podle názvu"""
    ent_upper = entitlement_id.upper()
    title_lower = title_name.lower()

    # 1. Kontrola podle entitlement_id (první sloupec CSV)
    # Reálné hry mají většinou na konci 'GAME00', 'BASEGAME', 'APPLICATION' apod.
    dlc_ent_keywords = [
        'DLC', 'SKIN', 'PACK', 'COSTUME', 'PASS', 'SOUNDTRACK', 'BGM',
        'VEHICLE', 'CONTENT', 'BONUS', 'COIN', 'POINTS', 'EXPANSION', 'ITEMS'
    ]
    for kw in dlc_ent_keywords:
        if kw in ent_upper:
            # Výjimka pokud by slovo bylo součástí slova GAME (např. GAMEPACK - raději odfiltrujeme)
            return True

    # 2. Kontrola podle názvu hry
    dlc_title_keywords = [
        'skin', 'costume', 'add-on', 'addon', 'expansion', 'season pass', 
        'deluxe edition pack', 'pre-order bonus', 'coin', 'points', 
        'dlc', 'bonus pack', 'item', 'bundle pack', 'soundtrack', 
        'vehicle', 'drone', 'car pack', 'train', 'content', 'swap'
    ]
    if any(kw in title_lower for kw in dlc_title_keywords):
        return True

    return False

def main():
    games_dict = {}

    # ----------------------------------------------------
    # KROK 1: Načtení dat z lokálního CSV souboru
    # ----------------------------------------------------
    print("1. Načítám databázi z lokálního CSV souboru...")
    
    if os.path.exists(LOCAL_CSV_PATH):
        try:
            with open(LOCAL_CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                # Načteme řádky s ošetřením, že první nepojmenovaný sloupec je entitlement_id
                reader = csv.reader(f)
                header = next(reader, None)

                rows_count = 0
                filtered_dlc_count = 0

                for row in reader:
                    if len(row) < 3:
                        continue
                    
                    rows_count += 1
                    entitlement_id = row[0].strip()
                    title_name = row[1].strip()
                    title_id = row[2].strip()
                    package_url = row[3].strip() if len(row) > 3 else ""

                    # Extrakce PPSA ID
                    ppsa_match = re.search(r'(PPSA\d{5})', title_id)
                    if not ppsa_match:
                        continue

                    ppsa = ppsa_match.group(1)

                    # Kontrola, zda se jedná o DLC nebo doplněk
                    if is_dlc_or_addon(entitlement_id, title_name):
                        filtered_dlc_count += 1
                        # Pokud už ale tento PPSA máme v databázi, uložíme si aspoň XML url pro určení FW
                        if ppsa in games_dict and package_url.startswith('http'):
                            games_dict[ppsa]["xml_urls"].add(package_url)
                        continue

                    # Pokud se jedná o plnou hru:
                    if ppsa not in games_dict:
                        games_dict[ppsa] = {
                            "title": title_name if title_name else ppsa,
                            "xml_urls": set()
                        }
                    else:
                        # Pokud již máme název (např. z kratšího záznamu), ponecháme čistý název hry
                        if len(title_name) > 0 and len(games_dict[ppsa]["title"]) == 9: # pokud tam bylo jen PPSA
                            games_dict[ppsa]["title"] = title_name

                    if package_url.startswith('http'):
                        games_dict[ppsa]["xml_urls"].add(package_url)

            print(f"   [OK] Přečteno {rows_count} řádků z {LOCAL_CSV_PATH}.")
            print(f"   [OK] Odfiltrováno {filtered_dlc_count} DLC/doplňků.")
            print(f"   [OK] Zachováno {len(games_dict)} unikátních plných PS5 her.")

        except Exception as e:
            print(f"   [!] Chyba při čtení souboru {LOCAL_CSV_PATH}: {e}")
    else:
        print(f"   [!] Soubor '{LOCAL_CSV_PATH}' nebyl nalezen!")

    # ----------------------------------------------------
    # KROK 2: Doplnění dat z GitHub TSV (Záložní zdroj)
    # ----------------------------------------------------
    print("2. Doplňuji historická data z GitHub TSV...")
    req_github = urllib.request.Request(GITHUB_TSV_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(req_github, timeout=15, context=ssl_context) as response:
            tsv_lines = response.read().decode('utf-8').splitlines()

            added_new = 0
            enriched_existing = 0

            for line in tsv_lines[1:]:
                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                content_id, title_name = parts[0].strip(), parts[1].strip()
                version_url = parts[2].strip() if len(parts) > 2 else ""

                if is_dlc_or_addon(content_id, title_name):
                    continue

                ppsa_match = re.search(r'(PPSA\d{5})', content_id)
                if not ppsa_match:
                    continue

                ppsa = ppsa_match.group(1)

                if ppsa in games_dict:
                    if version_url.startswith('http'):
                        games_dict[ppsa]["xml_urls"].add(version_url)
                        enriched_existing += 1
                else:
                    games_dict[ppsa] = {
                        "title": title_name,
                        "xml_urls": {version_url} if version_url.startswith('http') else set()
                    }
                    added_new += 1

            print(f"   Doplněno {enriched_existing} odkazů k existujícím hrám, přidáno {added_new} nových her z GitHubu.")

    except Exception as e:
        print(f"   [!] Chyba při stahování GitHub TSV: {e}")

    # ----------------------------------------------------
    # KROK 3: Stahování XML souborů a sestavení výsledku
    # ----------------------------------------------------
    print("3. Stahuji verze z XML a sestavuji výsledný JSON...")
    games_list = []
    total_games = len(games_dict)

    for idx, (ppsa, data) in enumerate(games_dict.items(), start=1):
        parsed_vers = []

        for url in data["xml_urls"]:
            raw_vers = fetch_xml_all_versions(url)
            for rv in raw_vers:
                f_str, f_num = parse_system_ver(rv)
                if f_str and f_num:
                    parsed_vers.append((f_num, f_str))

        min_fw_float = 0.0
        fw_display = "Neznámá"

        if parsed_vers:
            parsed_vers.sort(key=lambda x: x[0])
            
            min_fw_float = parsed_vers[0][0]
            min_fw_str = parsed_vers[0][1]
            max_fw_str = parsed_vers[-1][1]

            if min_fw_str == max_fw_str:
                fw_display = min_fw_str
            else:
                fw_display = f"{min_fw_str} ➔ {max_fw_str}"

        games_list.append({
            "platform": "PS5",
            "ppsa": ppsa,
            "title": data["title"],
            "minFw": min_fw_float,
            "fwDisplay": fw_display
        })

        if idx % 100 == 0 or idx == total_games:
            print(f"   Zpracováno {idx}/{total_games} her...")

    games_list.sort(key=lambda x: x['title'])

    os.makedirs("docs", exist_ok=True)
    output_path = "docs/ps5gamelist.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(games_list, f, ensure_ascii=False, indent=2)

    print("--------------------------------------------------")
    print(f"HOTOVO! Celkem vygenerováno {len(games_list)} unikátních plných her do {output_path}.")

if __name__ == "__main__":
    main()
