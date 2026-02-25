#!/usr/bin/env python3
"""
White Paper Index for Mission Control
Scans and catalogs Jason's white papers collection
"""

import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re

# === Configuration ===
PAPERS_ROOT = Path("/home/jwells/projects/white_papers/_drafts")
INDEX_PATH = Path(__file__).parent / "data" / "paper_index.json"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".md", ".txt", ".pptx"}

# === Domain Categories ===
DOMAIN_KEYWORDS = {
    "immersion_cooling": [
        "immersion", "dielectric", "coolant", "data center cooling", 
        "thermal management", "gpu cooling", "pue", "liquid cooling"
    ],
    "ev_fluids": [
        "ev drive", "electric vehicle", "e-axle", "transmission fluid",
        "ev thermal", "ev lubricant"
    ],
    "phase_change_materials": [
        "pcm", "phase change", "thermal storage", "latent heat",
        "building envelope"
    ],
    "mpao_products": [
        "mpao", "pao", "polyalphaolefin", "base oil", "synthetic lubricant"
    ],
    "financial": [
        "investment", "portfolio", "macro", "economic", "market", "investor"
    ],
    "physics": [
        "quantum", "spacetime", "electromagnetic", "fusion", "toroidal"
    ],
    "philosophy": [
        "philosophy", "liberty", "civilization", "morality", "enlightenment"
    ]
}


def get_file_hash(filepath: Path) -> str:
    """Get MD5 hash of file for change detection"""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(65536)  # Read first 64KB
            hasher.update(buf)
    except Exception:
        return ""
    return hasher.hexdigest()[:12]


def classify_paper(filename: str, folder: str) -> List[str]:
    """Classify paper into domains based on filename and folder"""
    text = f"{filename} {folder}".lower()
    domains = []
    
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                domains.append(domain)
                break
    
    return domains if domains else ["uncategorized"]


def extract_version(filename: str) -> Optional[str]:
    """Extract version number from filename"""
    # Match patterns like: v2, v12, V3, version 2
    match = re.search(r'v(\d+)', filename, re.IGNORECASE)
    if match:
        return f"v{match.group(1)}"
    return None


def scan_papers() -> Dict:
    """Scan the papers directory and build index"""
    index = {
        "papers": {},
        "by_domain": {},
        "by_folder": {},
        "stats": {
            "total_papers": 0,
            "total_size_mb": 0,
            "by_extension": {},
            "by_domain": {}
        },
        "scanned_at": datetime.now().isoformat()
    }
    
    if not PAPERS_ROOT.exists():
        print(f"Papers root not found: {PAPERS_ROOT}")
        return index
    
    for filepath in PAPERS_ROOT.rglob("*"):
        if not filepath.is_file():
            continue
        
        ext = filepath.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        
        # Get relative path and folder
        rel_path = filepath.relative_to(PAPERS_ROOT)
        folder = str(rel_path.parent) if rel_path.parent != Path(".") else "root"
        
        # Get file info
        stat = filepath.stat()
        size_mb = stat.st_size / 1024 / 1024
        
        # Classify
        domains = classify_paper(filepath.name, folder)
        version = extract_version(filepath.name)
        
        paper_id = str(rel_path)
        paper_info = {
            "id": paper_id,
            "name": filepath.name,
            "path": str(filepath),
            "folder": folder,
            "extension": ext,
            "size_mb": round(size_mb, 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "domains": domains,
            "version": version,
            "hash": get_file_hash(filepath)
        }
        
        index["papers"][paper_id] = paper_info
        
        # Index by domain
        for domain in domains:
            if domain not in index["by_domain"]:
                index["by_domain"][domain] = []
            index["by_domain"][domain].append(paper_id)
        
        # Index by folder
        if folder not in index["by_folder"]:
            index["by_folder"][folder] = []
        index["by_folder"][folder].append(paper_id)
        
        # Update stats
        index["stats"]["total_papers"] += 1
        index["stats"]["total_size_mb"] += size_mb
        index["stats"]["by_extension"][ext] = index["stats"]["by_extension"].get(ext, 0) + 1
        for domain in domains:
            index["stats"]["by_domain"][domain] = index["stats"]["by_domain"].get(domain, 0) + 1
    
    index["stats"]["total_size_mb"] = round(index["stats"]["total_size_mb"], 2)
    
    return index


def save_index(index: Dict) -> None:
    """Save index to file"""
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, 'w') as f:
        json.dump(index, f, indent=2)
    print(f"Index saved to {INDEX_PATH}")


def load_index() -> Optional[Dict]:
    """Load existing index"""
    try:
        with open(INDEX_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def print_summary(index: Dict) -> None:
    """Print index summary"""
    stats = index["stats"]
    print("\n" + "=" * 60)
    print("WHITE PAPER INDEX SUMMARY")
    print("=" * 60)
    print(f"\nTotal papers: {stats['total_papers']}")
    print(f"Total size: {stats['total_size_mb']:.1f} MB")
    
    print("\nBy extension:")
    for ext, count in sorted(stats["by_extension"].items(), key=lambda x: -x[1]):
        print(f"  {ext}: {count}")
    
    print("\nBy domain:")
    for domain, count in sorted(stats["by_domain"].items(), key=lambda x: -x[1]):
        print(f"  {domain}: {count}")
    
    print("\nBy folder:")
    for folder, papers in sorted(index["by_folder"].items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {folder}: {len(papers)}")
    
    print(f"\nScanned at: {index['scanned_at']}")


def search_papers(index: Dict, query: str) -> List[Dict]:
    """Search papers by query string"""
    query_lower = query.lower()
    results = []
    
    for paper_id, paper in index["papers"].items():
        score = 0
        
        # Name match (highest weight)
        if query_lower in paper["name"].lower():
            score += 10
        
        # Folder match
        if query_lower in paper["folder"].lower():
            score += 5
        
        # Domain match
        for domain in paper["domains"]:
            if query_lower in domain.lower():
                score += 3
        
        if score > 0:
            results.append({**paper, "score": score})
    
    return sorted(results, key=lambda x: -x["score"])


def find_related(index: Dict, paper_id: str) -> List[Dict]:
    """Find papers related to the given paper"""
    if paper_id not in index["papers"]:
        return []
    
    paper = index["papers"][paper_id]
    domains = set(paper["domains"])
    folder = paper["folder"]
    
    related = []
    for other_id, other in index["papers"].items():
        if other_id == paper_id:
            continue
        
        score = 0
        
        # Same folder
        if other["folder"] == folder:
            score += 5
        
        # Shared domains
        shared_domains = domains & set(other["domains"])
        score += len(shared_domains) * 3
        
        # Similar name (version variants)
        base_name = re.sub(r'\s*v\d+.*$', '', paper["name"], flags=re.IGNORECASE)
        other_base = re.sub(r'\s*v\d+.*$', '', other["name"], flags=re.IGNORECASE)
        if base_name.lower() == other_base.lower():
            score += 10
        
        if score > 0:
            related.append({**other, "score": score})
    
    return sorted(related, key=lambda x: -x["score"])[:10]


# === CLI ===

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "scan":
            print("Scanning papers...")
            index = scan_papers()
            save_index(index)
            print_summary(index)
            
        elif cmd == "summary":
            index = load_index()
            if index:
                print_summary(index)
            else:
                print("No index found. Run: python paper_index.py scan")
                
        elif cmd == "search" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            index = load_index()
            if index:
                results = search_papers(index, query)
                print(f"\nSearch results for '{query}':")
                for r in results[:15]:
                    print(f"  [{r['score']:2d}] {r['name']}")
                    print(f"       {r['folder']} | {', '.join(r['domains'])}")
            else:
                print("No index found. Run: python paper_index.py scan")
                
        else:
            print("Usage:")
            print("  python paper_index.py scan     - Scan and index papers")
            print("  python paper_index.py summary  - Show index summary")
            print("  python paper_index.py search <query>  - Search papers")
    else:
        # Default: scan
        print("Scanning papers...")
        index = scan_papers()
        save_index(index)
        print_summary(index)
