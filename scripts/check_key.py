from pathlib import Path
import re
p=Path('.env')
for line in p.read_text(encoding='utf-8-sig').splitlines():
    if line.startswith('DATA_GO_KR_SERVICE_KEY='):
        value=line.split('=',1)[1].strip().strip('\"\'')
        print({'length':len(value),'percent_encoded':'%' in value,'has_space':any(c.isspace() for c in value),'hex_only':bool(re.fullmatch('[0-9a-fA-F]+',value)),'inline_comment':'#' in value})
