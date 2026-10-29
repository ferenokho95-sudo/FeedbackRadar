import argparse
from common import ROOT,serve,save_json
from core import Radar,parse_csv,export_report

def routes(radar):
    def route(method,path,query,body):
        if method=='GET' and path=='/api/demo': return radar.analyze(parse_csv((ROOT/'data/reviews.csv').read_text(encoding='utf-8')))
        if method=='GET' and path=='/api/evaluation': return radar.evaluate()
        if method=='POST' and path=='/api/analyze': return radar.analyze(parse_csv(body.get('csv','')))
        if method=='POST' and path=='/api/correct': return radar.correct(body.get('review_id'),body.get('text'),body.get('topic'))
        raise LookupError()
    return route

def main():
    p=argparse.ArgumentParser(description='FeedbackRadar');p.add_argument('command',choices=['serve','demo','evaluate'],nargs='?',default='serve');p.add_argument('--port',type=int,default=8011);p.add_argument('--csv');p.add_argument('--out',default='reports/example');a=p.parse_args()
    radar=Radar()
    if a.command=='serve': serve(routes(radar),a.port,'FeedbackRadar')
    elif a.command=='evaluate':
        result=radar.evaluate();save_json(ROOT/a.out/'evaluation.json',result);print(result['classification']['macro avg'])
    else:
        path=ROOT/'data/reviews.csv' if not a.csv else __import__('pathlib').Path(a.csv)
        result=export_report(radar,parse_csv(path.read_text(encoding='utf-8-sig')),ROOT/a.out)
        print(f"Отзывов: {result['total']}, жалоб: {result['complaints']}, отчёт: {ROOT/a.out}")
if __name__=='__main__': main()
