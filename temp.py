import csv
EVENTS = {}
with open('datas/活動.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        eid = row['唯一識別碼']
        EVENTS[eid] = row
print(EVENTS["Event_A15010000H_081465"])