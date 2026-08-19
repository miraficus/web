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
    """Přísná detekce DLC, bonusů, skinů a doplňků"""
    ent_upper = entitlement_id.upper()
    title_lower = title_name.lower()

    # 1. Kontrola podle Entitlement ID (Kódy od Sony)
    ent_keywords = [
        'DLC', 'SKIN', 'PACK', 'COSTUME', 'PASS', 'SOUNDTRACK', 'BGM',
        'VEHICLE', 'CONTENT', 'BONUS', 'COIN', 'POINTS', 'EXPANSION', 
        'ITEM', 'PREORDER', 'REWARD', 'WEAPON', 'OUTFIT', 'AVATAR',
        'THEME', 'SUIT', 'ARMOR', 'CHARM', 'STORY', 'AHELP', 'DELUXE'
    ]
    for kw in ent_keywords:
        if kw in ent_upper:
            # Ujistíme se, že kód nekončí přímo jako plná aplikace/hra (např. GAME00 / BASEGAME)
            if not (ent_upper.endswith('GAME00000') or 'BASEGAME' in ent_upper):
                return True

    # 2. Kontrola podle názvu (Title)
    title_keywords = [
        'skin', 'costume', 'add-on', 'addon', 'expansion', 'season pass', 
        'deluxe edition pack', 'pre-order', 'preorder', 'reward', 'bonus', 
        'coin', 'points', 'dlc', 'bonus pack', 'item', 'bundle pack', 
        'soundtrack', 'vehicle', 'drone', 'car pack', 'train', 'content', 
        'swap', 'weapon', 'outfit', 'armor', 'charm', 'suite', 'steak', 
        'pacote', 'fortalecimento', 'ajuda', 'story expansion', 'character',
        'digital deluxe', 'deluxe content'
    ]
    if any(kw in title_lower for kw in title_keywords):
        return True

    # 3. Detekce asijských znaků typických pro speciální DLC edice
    if re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', title_name):
        # Pokud název obsahuje např. <數位豪華版限定> (Digital Deluxe Bonus)
        if any(c in title_name for c in ['限定', '特典', '豪華', 'パック', '衣装']):
            return True

    return False

def main():
    games_dict = {}  # ppsa -> { title: str, is_clean_game: bool, xml_urls: set() }

    # ----------------------------------------------------
    # KROK 1: Načtení dat z lokálního CSV souboru
    # ----------------------------------------------------
    print("1. Načítám databázi z lokálního CSV souboru...")
    
    if os.path.exists(LOCAL_CSV_PATH):
        try:
            with open(LOCAL_CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
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
                    is_dlc = is_dlc_or_addon(entitlement_id, title_name)

                    if is_dlc:
                        filtered_dlc_count += 1

                    # Pokud PPSA ještě v databázi nemáme:
                    if ppsa not in games_dict:
                        games_dict[ppsa] = {
                            "title": title_name if not is_dlc else ppsa,
                            "is_clean_game": not is_dlc,
                            "xml_urls": set()
                        }
                    else:
                        # Pokud už PPSA v databázi máme, ale byl tam název z DLC (nebo jen PPSA), 
                        # a teď přišel čistý název hry, nahradíme ho!
                        if not games_dict[ppsa]["is_clean_game"] and not is_dlc:
                            games_dict[ppsa]["title"] = title_name
                            games_dict[ppsa]["is_clean_game"] = True

                    # Odkazy na XML sbíráme vždy pro nejpřesnější FW
                    if package_url.startswith('http'):
                        games_dict[ppsa]["xml_urls"].add(package_url)

            print(f"   [OK] Přečteno {rows_count} řádků z {LOCAL_CSV_PATH}.")
            print(f"   [OK] Odfiltrováno {filtered_dlc_count} DLC/doplňků.")
            print(f"   [OK] Zachováno {len(games_dict)} unikátních PS5 her.")

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

                is_dlc = is_dlc_or_addon(content_id, title_name)

                ppsa_match = re.search(r'(PPSA\d{5})', content_id)
                if not ppsa_match:
                    continue

                ppsa = ppsa_match.group(1)

                if ppsa in games_dict:
                    # Pokud v databázi nemáme čistý název a z GitHubu přišel název plné hry:
                    if not games_dict[ppsa]["is_clean_game"] and not is_dlc:
                        games_dict[ppsa]["title"] = title_name
                        games_dict[ppsa]["is_clean_game"] = True

                    if version_url.startswith('http'):
                        games_dict[ppsa]["xml_urls"].add(version_url)
                        enriched_existing += 1
                else:
                    if not is_dlc:
                        games_dict[ppsa] = {
                            "title": title_name,
                            "is_clean_game": True,
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
    
    # Vyfiltrujemy pouze ty PPSA, které mají platný čistý název hry (vyřadí sirotčí DLC)
    valid_games = {k: v for k, v in games_dict.items() if v["is_clean_game"]}
    total_games = len(valid_games)

    for idx, (ppsa, data) in enumerate(valid_games.items(), start=1):
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
    print(f"HOTOVO! Celkem vygenerováno {len(games_list)} čistých PS5 her do {output_path}.")

if __name__ == "__main__":
    main()
