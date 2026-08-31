import re

str1 = open("apache-log-parse.input.log").read()
str1_strings2 = re.findall(r'(^)([0-9\.]*)([^"]*)(")([A-Z]*)(.*)(HTTP/1\.)(\d*)("\ )(\d*)', str1, flags=re.M)  #%click [{"expr": "$[1]"}, {"expr": "$[4]"}, {"expr": "$[5]"}, {"expr": "$[6]"}, {"expr": "$[7]"}, {"expr": "$[8]"}, {"expr": "$[9]"}]
str1_strings = re.findall(r'.{11}', str1, flags=re.M)