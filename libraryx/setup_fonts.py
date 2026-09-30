import os
import urllib.request
import zipfile
import io

# Colors for terminal printing
GREEN = '\033[92m'
RED = '\033[91m'
NC = '\033[0m'

FONTS_DIR = '/home/tchoua/Desktop/soutenencee/libraryx/libraryx/assets/fonts'

# Font URLs list
font_urls = {
    # Poppins Fonts
    'Poppins-Bold.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf',
    'Poppins-Medium.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Medium.ttf',
    'Poppins-SemiBold.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBold.ttf',
    'Poppins-ExtraBold.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-ExtraBold.ttf',
    'Poppins-BoldItalic.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-BoldItalic.ttf',
    'Poppins-MediumItalic.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-MediumItalic.ttf',
    'Poppins-SemiBoldItalic.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-SemiBoldItalic.ttf',
    'Poppins-ExtraBoldItalic.ttf': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-ExtraBoldItalic.ttf',
    
    # Gill Sans Ultra Bold
    'GILSANUB.TTF': 'https://raw.githubusercontent.com/aaron-v/Windows-10-Fonts/master/GILSANUB.TTF'
}

def download_file(url, path):
    print(f"Downloading {url} ...", flush=True)
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req) as response:
        with open(path, 'wb') as out_file:
            out_file.write(response.read())
    print(f"{GREEN}Saved to {path}{NC}", flush=True)

def setup():
    if not os.path.exists(FONTS_DIR):
        print(f"Creating fonts directory: {FONTS_DIR} ...", flush=True)
        os.makedirs(FONTS_DIR, exist_ok=True)
        
    # Download standard fonts
    for font_name, url in font_urls.items():
        dest = os.path.join(FONTS_DIR, font_name)
        if not os.path.exists(dest):
            try:
                download_file(url, dest)
            except Exception as e:
                print(f"{RED}Failed to download {font_name}: {e}{NC}", flush=True)
        else:
            print(f"{font_name} already exists.", flush=True)

    # Download Bassy list zip
    bassy_dest = os.path.join(FONTS_DIR, 'BassyRegular.ttf')
    if not os.path.exists(bassy_dest):
        bassy_url = 'https://dl.dafont.com/dl/?f=bassy'
        try:
            print(f"Downloading Bassy zip from {bassy_url} ...", flush=True)
            req = urllib.request.Request(
                bassy_url,
                headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
            )
            with urllib.request.urlopen(req) as response:
                zip_data = response.read()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                # Find the ttf file in the zip
                ttf_filename = None
                for name in z.namelist():
                    if name.lower().endswith('.ttf'):
                        ttf_filename = name
                        break
                if ttf_filename:
                    with open(bassy_dest, 'wb') as f:
                        f.write(z.read(ttf_filename))
                    print(f"{GREEN}Successfully unzipped and saved BassyRegular.ttf{NC}", flush=True)
                else:
                    print(f"{RED}No .ttf file found in Bassy zip.{NC}", flush=True)
        except Exception as e:
            print(f"{RED}Failed to download Bassy: {e}{NC}", flush=True)
    else:
        print("BassyRegular.ttf already exists.", flush=True)

if __name__ == '__main__':
    setup()
