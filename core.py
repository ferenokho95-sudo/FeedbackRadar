"""Supervised topic classification and transparent complaint prioritization."""
import csv, io, re, hashlib
from datetime import date
from collections import Counter
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from common import ROOT, connect, read_json, save_json

LABELS=['оплата','доставка','интерфейс','поддержка']
THRESHOLD=.45  # fixed before holdout evaluation, not tuned on holdout
ISSUES={
 'оплата':[('Двойное списание',('дважды','двойн','повторно'),5),('Возврат денег',('возврат','вернул','вернут'),4)],
 'доставка':[('Опоздание доставки',('опозд','задерж','позже','срок'),4),('Повреждение заказа',('разбит','повреж','мят'),5)],
 'интерфейс':[('Сбой приложения',('вылет','завис','ошиб','сбой'),4),('Неудобный поиск',('поиск','найти','фильтр'),3)],
 'поддержка':[('Долгое ожидание ответа',('жду','долго','час','ответ'),4),('Нерешённый вопрос',('реш','помог'),3)]}

def norm(text): return ' '.join(re.findall(r'\w+',text.lower()))

def parse_csv(text):
    if len(text)>1_500_000: raise ValueError('CSV больше 1.5 МБ')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not {'review_id','text','rating','date'}<=set(reader.fieldnames or []):
        raise ValueError('Нужны столбцы review_id,text,rating,date')
    rows=[]; ids=set()
    for n,r in enumerate(reader,2):
        rid=(r.get('review_id') or '').strip();body=(r.get('text') or '').strip()
        if not rid or rid in ids or len(rid)>80: raise ValueError(f'Строка {n}: пустой/повторный review_id')
        if len(body)<3 or len(body)>6000: raise ValueError(f'Строка {n}: текст 3..6000 символов')
        try: rating=int(r['rating']);date.fromisoformat(r['date'])
        except (ValueError,TypeError): raise ValueError(f'Строка {n}: rating 1..5 и date YYYY-MM-DD') from None
        if rating not in range(1,6): raise ValueError(f'Строка {n}: rating 1..5')
        ids.add(rid);rows.append({'review_id':rid,'text':body,'rating':rating,'date':r['date']})
        if len(rows)>5000: raise ValueError('Не более 5000 отзывов')
    if not rows: raise ValueError('CSV не содержит отзывов')
    return rows

class Radar:
    def __init__(self,db_path=None):
        self.db_path=db_path
        train=read_json(ROOT/'data/train.json')
        if set(r['topic'] for r in train)!=set(LABELS): raise ValueError('В train нужны все 4 категории')
        self.model=make_pipeline(TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),sublinear_tf=True),
                                 LogisticRegression(C=6,max_iter=1000,random_state=42))
        self.model.fit([r['text'] for r in train],[r['topic'] for r in train])
        self.train=train
        with connect(db_path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS corrections(review_id TEXT PRIMARY KEY,text_hash TEXT NOT NULL,topic TEXT NOT NULL)')
    def classify(self,text):
        probs=self.model.predict_proba([text])[0];i=int(probs.argmax());confidence=float(probs[i])
        return {'topic':str(self.model.classes_[i]) if confidence>=THRESHOLD else 'проверить вручную',
                'top_topic':str(self.model.classes_[i]),'confidence':round(confidence,4)}
    def correct(self,rid,text,topic):
        if topic not in LABELS: raise ValueError('Неизвестная категория')
        if not isinstance(rid,str) or not rid or not isinstance(text,str) or not text: raise ValueError('Нужны review_id и text')
        digest=hashlib.sha256(text.encode()).hexdigest()
        with connect(self.db_path) as db:
            db.execute('INSERT OR REPLACE INTO corrections VALUES (?,?,?)',(rid,digest,topic))
        return {'saved':True}
    def analyze(self,rows):
        with connect(self.db_path) as db: corrections={r['review_id']:dict(r) for r in db.execute('SELECT * FROM corrections')}
        output=[];seen=set();duplicates=0
        for r in rows:
            normalized=norm(r['text'])
            if normalized in seen: duplicates+=1;continue
            seen.add(normalized);c=self.classify(r['text']);corrected=False
            correction=corrections.get(r['review_id'])
            if correction and correction['text_hash']==hashlib.sha256(r['text'].encode()).hexdigest():
                c['topic']=correction['topic'];corrected=True
            topic=c['topic'];issue='Общая жалоба';severity=3
            if topic in ISSUES:
                for name,keywords,level in ISSUES[topic]:
                    if any(word in r['text'].lower() for word in keywords): issue,severity=name,level;break
            output.append(dict(r,**c,corrected=corrected,complaint=r['rating']<=3,issue=issue,severity=severity))
        backlog=[]
        for topic,issue in sorted({(r['topic'],r['issue']) for r in output if r['complaint']}):
            group=[r for r in output if r['complaint'] and r['topic']==topic and r['issue']==issue]
            severity=max(r['severity'] for r in group)
            backlog.append({'topic':topic,'issue':issue,'count':len(group),'severity':severity,
              'score':round(100*len(group)/len(output)*severity/5,2),
              'examples':[{'review_id':r['review_id'],'text':r['text']} for r in group[:3]],
              'hypothesis':f'Исследовать «{issue.lower()}»: проверить сценарий и подтвердить причину на обращениях.'})
        backlog.sort(key=lambda r:(-r['score'],-r['count'],r['topic']))
        return {'rows':output,'backlog':backlog,'topics':dict(Counter(r['topic'] for r in output)),
                'total':len(output),'duplicates_removed':duplicates,'complaints':sum(r['complaint'] for r in output),
                'manual_review':sum(r['topic']=='проверить вручную' for r in output),
                'method':'score = 100 × доля жалоб на проблему среди всех уникальных отзывов × severity / 5',
                'data_origin':'Демонстрационные данные при использовании комплектного CSV; загруженный CSV — данные пользователя.'}
    def evaluate(self):
        test=read_json(ROOT/'data/test.json')
        if {norm(r['text']) for r in self.train}&{norm(r['text']) for r in test}: raise ValueError('Утечка: одинаковые тексты train/test')
        gold=[r['topic'] for r in test];items=[dict(r,expected_topic=r['topic'],**self.classify(r['text'])) for r in test]
        pred=[r['top_topic'] for r in items]
        accepted=[r for r in items if r['topic']!='проверить вручную']
        return {'source':'Синтетический независимый holdout; не оценка на клиентах',
          'train_count':len(self.train),'test_count':len(test),'threshold':THRESHOLD,
          'classification':classification_report(gold,pred,labels=LABELS,output_dict=True,zero_division=0),
          'confusion_matrix':confusion_matrix(gold,pred,labels=LABELS).tolist(),'labels':LABELS,
          'coverage':len(accepted)/len(items),'accepted_accuracy':sum(r['topic']==r['top_topic'] and r['top_topic']==test[i]['topic'] for i,r in enumerate(items) if r['topic']!='проверить вручную')/len(accepted) if accepted else None,
          'items':items}

def export_report(radar,rows,out):
    report=radar.analyze(rows);evaluation=radar.evaluate();out.mkdir(parents=True,exist_ok=True)
    save_json(out/'analysis.json',report);save_json(out/'evaluation.json',evaluation)
    lines=['# FeedbackRadar — отчёт','', 'Данные демонстрационные, эффект на бизнес не измерялся.',
      f"Уникальных отзывов: {report['total']}; жалоб: {report['complaints']}; ручная проверка: {report['manual_review']}.",
      f"Holdout macro-F1: {evaluation['classification']['macro avg']['f1-score']:.4f}.",'',report['method'],'',
      '| Приоритет | Тема | Проблема | Жалобы | Score |','|---|---|---|---:|---:|']
    lines += [f"| {i} | {r['topic']} | {r['issue']} | {r['count']} | {r['score']} |" for i,r in enumerate(report['backlog'],1)]
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    return report
