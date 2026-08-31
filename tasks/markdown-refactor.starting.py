# Starting code: a working but clunky Markdown -> HTML converter.
# Supports: headings (# .. ######), * bullet lists, __bold__, _italic_, paragraphs.

def parse(markdown):
    lines = markdown.split('\n')
    res = ''
    in_list = False
    in_list_after = False
    for i in lines:
        if i.startswith('###### '):
            i = '<h6>' + i[7:] + '</h6>'
        elif i.startswith('##### '):
            i = '<h5>' + i[6:] + '</h5>'
        elif i.startswith('#### '):
            i = '<h4>' + i[5:] + '</h4>'
        elif i.startswith('### '):
            i = '<h3>' + i[4:] + '</h3>'
        elif i.startswith('## '):
            i = '<h2>' + i[3:] + '</h2>'
        elif i.startswith('# '):
            i = '<h1>' + i[2:] + '</h1>'
        if i.startswith('* '):
            if not in_list:
                in_list = True
                is_bold = False
                is_italic = False
                curr = i[2:]
                if curr.count('__') >= 2:
                    curr = curr.replace('__', '<strong>', 1)
                    curr = curr.replace('__', '</strong>', 1)
                    is_bold = True
                if curr.count('_') >= 2:
                    curr = curr.replace('_', '<em>', 1)
                    curr = curr.replace('_', '</em>', 1)
                    is_italic = True
                i = '<ul><li>' + curr + '</li>'
            else:
                is_bold = False
                is_italic = False
                curr = i[2:]
                if curr.count('__') >= 2:
                    curr = curr.replace('__', '<strong>', 1)
                    curr = curr.replace('__', '</strong>', 1)
                    is_bold = True
                if curr.count('_') >= 2:
                    curr = curr.replace('_', '<em>', 1)
                    curr = curr.replace('_', '</em>', 1)
                    is_italic = True
                i = '<li>' + curr + '</li>'
        else:
            if in_list:
                in_list_after = True
                in_list = False

        if not i.startswith('<h') and not i.startswith('<ul') and not i.startswith('<li'):
            i = '<p>' + i + '</p>'
        if i.count('__') >= 2:
            i = i.replace('__', '<strong>', 1)
            i = i.replace('__', '</strong>', 1)
        if i.count('_') >= 2:
            i = i.replace('_', '<em>', 1)
            i = i.replace('_', '</em>', 1)
        if in_list_after:
            i = '</ul>' + i
            in_list_after = False
        res += i
    if in_list:
        res += '</ul>'
    return res

with open('markdown-refactor.input.md') as f:
    print(parse(f.read().rstrip('\n')))
