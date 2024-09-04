from flask import Flask, request, render_template_string, redirect, url_for
import os
import requests
from bs4 import BeautifulSoup
from lxml import etree
from urllib.parse import urljoin
import json
import pandas as pd
from PyPDF2 import PdfReader
from zipfile import ZipFile
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Folder to save downloaded PDFs and metadata
DOWNLOAD_FOLDER = "bearClaw_data"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# List to store metadata
metadata_list = []

def get_document_urls(page_url):
    try:
        response = requests.get(page_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        
        document_urls = []
        for h3 in soup.find_all('h3', class_='title'):
            atag = h3.find('a')
            if atag and 'href' in atag.attrs:
                full_url = urljoin(page_url, atag['href'])
                document_urls.append(full_url)
        
        logging.debug(f"Document URLs found: {document_urls}")
        return document_urls
    except requests.RequestException as e:
        logging.error(f"Failed to get document URLs: {e}")
        return []

def extract_pdf_metadata(pdf_path):
    try:
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
            info = reader.metadata
            return {
                "Document Creation Date": info.get('/CreationDate', 'Unknown'),
                "Document Page Count": len(reader.pages),
                "Author": info.get('/Author', 'Unknown'),
                "Original Classification": info.get('/Subject', 'Unknown'),
            }
    except Exception as e:
        logging.error(f"Failed to extract PDF metadata: {e}")
        return {}

def extract_from_xpath(soup, xpath):
    try:
        tree = etree.HTML(str(soup))
        element = tree.xpath(xpath)
        return element[0].text.strip() if element else 'Unknown'
    except Exception as e:
        logging.error(f"Failed to extract data from XPath: {e}")
        return 'Unknown'

def download_pdf_and_collect_metadata(doc_url):
    try:
        response = requests.get(doc_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        pdf_link = None
        for a_tag in soup.find_all('a', href=True):
            if 'pdf' in a_tag['href'].lower() or 'pdf' in a_tag.get_text(strip=True).lower():
                pdf_link = a_tag
                break
        
        if pdf_link:
            pdf_url = urljoin("https://www.cia.gov", pdf_link['href'])
            basename = os.path.basename(pdf_url)
            pdf_path = os.path.join(DOWNLOAD_FOLDER, basename)
            logging.info(f"Storing {basename} at {pdf_path}...")
            
            try:
                pdf_content = requests.get(pdf_url).content
                with open(pdf_path, 'wb') as f:
                    f.write(pdf_content)
                logging.info(f"{basename} stored at {pdf_path}.")
                
                pdf_metadata = extract_pdf_metadata(pdf_path)
                metadata = {
                    "source_url": doc_url,
                    "PDF Path": pdf_path,
                    "Document Type": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[1]/div[2]/div/a'),
                    "Collection": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[2]/div[2]/div/a'),
                    "Document Number (FOIA) /ESDN (CREST)": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[3]/div[2]/div'),
                    "Release Decision": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[4]/div[2]/div'),
                    "Original Classification": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[5]/div[2]/div'),
                    "Document Page Count": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[6]/div[2]/div'),
                    "Document Creation Date": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[7]/div[2]/div/span'),
                    "Document Release Date": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[9]/div[2]/div'),
                    "Sequence Number": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[8]/div[2]/div'),
                    "Original Publication Date": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[11]/div[2]/div/span'),
                    "Content Type": extract_from_xpath(soup, '/html/body/div/div[1]/section/div/div[2]/article/div/div/div/div/div/div/div[1]/div[12]/div[2]/div'),
                    "Body": soup.find('div', class_='field-item even').get_text(strip=True) if soup.find('div', class_='field-item even') else 'No Description Found'
                }
                
                logging.info(f"Collected Metadata: {metadata}")
                metadata_list.append(metadata)
            except requests.RequestException as e:
                logging.error(f"Failed to store PDF: {e}")
        else:
            logging.warning(f"PDF link not found on {doc_url}")
    except requests.RequestException as e:
        logging.error(f"Failed to download document: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        base_url = request.form.get('base_url').strip()
        num_pages = int(request.form.get('num_pages').strip())

        global metadata_list
        metadata_list = []  # Reset the metadata list

        # Start processing
        for page_number in range(num_pages):
            logging.info(f"Processing page {page_number}...")
            page_url = f"{base_url}?page={page_number}"
            document_urls = get_document_urls(page_url)
            if not document_urls:
                logging.info("No more documents found. Exiting...")
                break

            for doc_url in document_urls:
                download_pdf_and_collect_metadata(doc_url)

        # Save metadata to JSON
        metadata_file = os.path.join(DOWNLOAD_FOLDER, "metadata.json")
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata_list, f, indent=4, ensure_ascii=False)
            logging.info(f"Metadata saved to {metadata_file}")
        except IOError as e:
            logging.error(f"Failed to save metadata JSON: {e}")

        # Save metadata to Excel
        df = pd.DataFrame(metadata_list)
        excel_file = os.path.join(DOWNLOAD_FOLDER, "metadata.xlsx")
        try:
            df.to_excel(excel_file, index=False)
            logging.info(f"Metadata exported to Excel: {excel_file}")
        except IOError as e:
            logging.error(f"Failed to save metadata Excel: {e}")
        
        # Save metadata to TSV (tab-delimited file)
        tsv_file = os.path.join(DOWNLOAD_FOLDER, "metadata.tsv")
        try:
            df.to_csv(tsv_file, sep='\t', index=False)
            logging.info(f"Metadata exported to TSV: {tsv_file}")
        except IOError as e:
            logging.error(f"Failed to save metadata TSV: {e}")

        # Create a ZIP file of all PDFs
        zip_file_path = os.path.join(DOWNLOAD_FOLDER, 'pdfs.zip')
        try:
            with ZipFile(zip_file_path, 'w') as zipf:
                for root, _, files in os.walk(DOWNLOAD_FOLDER):
                    for file in files:
                        if file.endswith('.pdf'):
                            zipf.write(os.path.join(root, file), file)
            logging.info(f"PDFs zipped into: {zip_file_path}")
        except IOError as e:
            logging.error(f"Failed to create ZIP file: {e}")

        return redirect(url_for('results'))

    return render_template_string('''
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>bearClaw</title>
    <style>
        body {
            background-color: #77815C;
            font-family: "Courier New", Courier, monospace;
            color: white;
        }
    </style>
</head>
<body>
    <h1>welcome to bearClaw</h1>
    <form method="post">
        <label for="base_url">Base URL:</label>
        <input type="text" id="base_url" name="base_url" required><br>
        <label for="num_pages">Number of Pages to Search:</label>
        <input type="number" id="num_pages" name="num_pages" min="1" required><br>
        <input type="submit" value="start scraping">
    </form>
</body>
</html>
''')

@app.route('/results')
def results():
    return render_template_string('''
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Download Results</title>
    <style>
        body {
            background-color: #77815C;
            font-family: "Courier New", Courier, monospace;
            color: white;
        }
    </style>
</head>
<body>
    <h1>Results</h1>
    <p>Your documents have been downloaded and processed. All files are available in the <strong>bearClaw_data</strong> directory.</p>
</body>
</html>
''')

if __name__ == '__main__':
    app.run(debug=True)
