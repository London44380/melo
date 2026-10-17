# melo — Mail Extractor Locator

Parcourt un ou plusieurs sites web et en extrait toutes les adresses email trouvées.

![Démo : page de test locale, données fictives](docs/demo.gif)

## Prérequis
```
pip install requests
```

## Usage
```
python3 melo.py https://exemple.com
python3 melo.py https://exemple.com -d 2 -o emails.txt
python3 melo.py exemple.com autresite.com --json out.json
```

## Options
| Option | Rôle |
|---|---|
| `urls` | Une ou plusieurs URLs de site |
| `-d`, `--depth` | Profondeur de crawl (défaut 1) |
| `-m`, `--max-pages` | Pages max visitées (défaut 100) |
| `-t`, `--timeout` | Timeout de requête (défaut 10 s) |
| `--delay` | Délai entre requêtes (politesse) |
| `-o`, `--output` | Liste brute des emails |
| `--json` | Emails + pages sources en JSON |
| `-q`, `--quiet` | Masque la progression |
