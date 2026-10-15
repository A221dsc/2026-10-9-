"""Rebuild scientific S2 figures from derived CSV; never runs experiments."""
import argparse,csv,hashlib,json,sys
from pathlib import Path

def read(p):
    with p.open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
def bind(p):return {'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--deps',type=Path);a=p.parse_args()
    if a.deps:sys.path.insert(0,str(a.deps.resolve()))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    a.output.mkdir(parents=True,exist_ok=False)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})
    inputs=['native_summary.csv','aa_floor.json','resource_snapshots.csv','resource_paired.csv','resource_summary.csv']
    summary=read(a.input/inputs[0]);floor=json.loads((a.input/'aa_floor.json').read_text())
    colors={'M_LIST':'#0072B2','M_EVENT_16':'#009E73','R6':'#D55E00','TLX':'#6A51A3'}
    labels={'M_LIST':'Matched LIST','M_EVENT_16':'Event16','R6':'Adaptive R6','TLX':'TLX'}
    def save(fig,name):
        for ext in ('png','svg'):fig.savefig(a.output/(name+'.'+ext),bbox_inches='tight')
        plt.close(fig)
    fig,axes=plt.subplots(3,2,figsize=(11,10),sharex=True,sharey=True)
    low=min(float(r['q25']) for r in summary if r['component']!='build')*.85
    high=max(float(r['q75']) for r in summary if r['component']!='build')*1.2
    for i,load in enumerate(('L01','L02','L03')):
        for j,component in enumerate(('online','total')):
            ax=axes[i,j];d=floor['components'][component]['D'];ax.axhspan(np.exp(-d),np.exp(d),color='#eeeeee',zorder=0);ax.axhline(1,color='#777777',linewidth=.8)
            for ref in ('M_LIST','M_EVENT_16','TLX'):
                rows=sorted((r for r in summary if r['case_id']==load and r['component']==component and r['reference']==ref),key=lambda r:int(r['horizon']))
                x=[int(r['horizon']) for r in rows];y=[float(r['median']) for r in rows]
                ax.plot(x,y,'o-',color=colors[ref],label='R6 / '+labels[ref],linewidth=1.7,markersize=4)
                ax.fill_between(x,[float(r['q25']) for r in rows],[float(r['q75']) for r in rows],color=colors[ref],alpha=.15)
            ax.set_yscale('log');ax.set_ylim(low,high);ax.set_yticks([.5,1,2,4],['0.5','1','2','4']);ax.set_title(load+' | '+('Online' if component=='online' else 'Build + online'));ax.grid(axis='y',alpha=.18)
            if j==0:ax.set_ylabel('Paired time ratio (log scale)')
            if i==2:ax.set_xlabel('Window turnovers');ax.set_xticks([1,2,4])
    axes[0,0].legend(fontsize=8,loc='upper left');fig.suptitle('True-prefix cumulative costs on NASA timestamps',fontsize=14,y=1.01)
    fig.text(.5,.003,'Lines: median; colored bands: Q25-Q75 across ten seeds (not confidence intervals).\nGray band: frozen practical/noise threshold. L03 at 1 turnover precedes the shuffled phase.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.045,1,1));save(fig,'S2_累计成本')
    snaps=read(a.input/'resource_snapshots.csv');fig,axes=plt.subplots(2,1,figsize=(11,7),sharex=True)
    selected=[r for r in snaps if r['case_id']=='L03' and r['seed']=='100001']
    for method in ('M_LIST','M_EVENT_16','R6','TLX'):
        rows=sorted((r for r in selected if r['method']==method),key=lambda r:int(r['unit']));x=[int(r['unit'])/262144 for r in rows]
        if method!='TLX':axes[0].plot(x,[int(r['final_tree_buckets']) for r in rows],'o--',color=colors[method],label=labels[method])
        axes[1].plot(x,[int(r['whole_current'])/2**20 for r in rows],'o--',color=colors[method],label=labels[method])
    axes[0].axhline(32,color='#555555',linestyle=':',label='Tree budget K=32');axes[0].set_ylabel('Current TREE buckets');axes[0].legend(ncol=4,fontsize=9)
    axes[1].set_ylabel('Whole current requested MiB');axes[1].set_xlabel('Window turnovers');axes[1].legend(ncol=4,fontsize=9)
    for ax in axes:
        for boundary in (349525/262144,699050/262144):ax.axvline(boundary,color='#999999',linewidth=.9)
        ax.grid(alpha=.18);ax.set_xlim(.95,4.05)
    axes[0].set_title('L03 resource checkpoints | lowest registered seed 100001')
    fig.text(.5,.002,'Both panels use the same resource run per method; no native-time trajectory is joined.\nMarkers are measured checkpoints; dashed connections do not show unobserved intra-phase changes.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.055,1,1));save(fig,'S2_漂移资源检查点')
    rows=sorted((r for r in read(a.input/'resource_paired.csv') if r['case_id']=='L03' and r['reference']=='M_EVENT_16'),key=lambda r:int(r['seed']))
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,key,title in zip(axes,('promotions_ratio','whole_peak_ratio'),('Promotion count','Whole peak requested bytes')):
        x=[int(r['seed'])-100000 for r in rows];y=[float(r[key]) for r in rows];median=float(np.median(y))
        ax.plot(x,y,'o-',color=colors['R6']);ax.axhline(1,color='#777777',linestyle=':');ax.axhline(median,color=colors['M_EVENT_16'],linestyle='--',label=f'Median={median:.4f}')
        ax.set_ylim(0,1.05);ax.set_xticks(x);ax.set_xlabel('Seed minus 100000');ax.set_ylabel('R6 / Event16');ax.set_title(title);ax.legend();ax.grid(alpha=.15)
    fig.suptitle('L03 paired resource effects at four turnovers');fig.tight_layout();save(fig,'S2_转换与峰值空间')
    rs=read(a.input/'resource_summary.csv');fig,axes=plt.subplots(1,3,figsize=(12,4),sharey=True);methods=('M_LIST','M_EVENT_16','R6','TLX');x=np.arange(4)
    for ax,load in zip(axes,('L01','L02','L03')):
        rows=[next(r for r in rs if r['case_id']==load and r['method']==m) for m in methods]
        ax.bar(x-.18,[float(r['whole_current_median'])/2**20 for r in rows],.36,label='Final current',color='#377EB8');ax.bar(x+.18,[float(r['whole_peak_median'])/2**20 for r in rows],.36,label='Simultaneous peak',color='#E69F00')
        ax.set_xticks(x,['LIST','Event16','R6','TLX']);ax.set_title(load);ax.grid(axis='y',alpha=.15)
    axes[0].set_ylabel('Requested MiB (median of ten runs)');axes[0].legend(fontsize=8);fig.suptitle('Resource-only batch | full four-turnover horizon')
    fig.text(.5,.005,'Final-current and peak medians are separate summaries; requested bytes are not process RSS.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.06,1,1));save(fig,'S2_内存汇总')
    manifest={'status':'COMPLETE','python':sys.executable,'python_version':sys.version,'matplotlib':matplotlib.__version__,'numpy':np.__version__,'plot_packages':str(a.deps.resolve()) if a.deps else None,'source':[bind(a.input/n) for n in inputs],'script':bind(Path(__file__)),'selected_resource_seed':100001,'selection_rule':'lowest registered seed; all ten seeds preserved in CSV','no_benchmark_execution':True,'files':[bind(p) for p in sorted(a.output.iterdir())]}
    (a.output/'figure_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('COMPLETE: 4 figures in PNG and SVG')
if __name__=='__main__':main()
