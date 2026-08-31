import re

str1 = open("apache-log-parse.input.log").read()
str1_strings3 = re.findall(r'(")([A-Z]*)(\ )(.*)(\ HTTP/1\.)', str1, flags=re.M)
str1_strings3_grouped = dict(sorted((_d := {}, [_d.setdefault(item[3], []).append(item) for item in str1_strings3])[0].items(), key=lambda item: len(item[1]), reverse=True))  #%click [{"expr": "$k"}, {"expr": "len($v)"}]
