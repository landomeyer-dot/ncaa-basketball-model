"""Refresh NCAA Four Factors and join official SportsDataverse game schedule.
Run: python build_ncaa_four_factors_v3.py --season 2027
Produces season aggregate and (only if all game dates map) prior-day snapshots.
"""
import argparse
from pathlib import Path
import pandas as pd
import requests

BASE='https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{tag}_{season}.parquet'
METRICS=['fga','fgm','tpa','tpm','fta','orb','drb','to','d_fga','d_fgm','d_tpa','d_tpm','d_fta','d_orb','d_drb','d_to']
def fetch(tag,season,out):
    path=out/f'{tag}_{season}.parquet'; temp=out/f'{tag}_{season}.part'
    url=BASE.format(tag=tag,season=season)
    print('Downloading:',url,flush=True)
    try:
        with requests.get(url,stream=True,timeout=120,headers={'User-Agent':'NCAA-Four-Factors-Research/1.0'}) as response:
            response.raise_for_status()
            with temp.open('wb') as f:
                for block in response.iter_content(1024*1024):
                    if block:f.write(block)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return pd.read_parquet(path)
def divide(a,b):return a.div(b.where(b.ne(0)))
def factors(df,games,season,dates=None):
    c=lambda name:df[name]
    fga=c('fga');opp=c('d_fga')
    return pd.DataFrame({'team':df['team'],'season':season,'as_of_date':dates if dates is not None else '',
      'games':games,'two_point_pct':divide(c('fgm')-c('tpm'),fga-c('tpa')),
      'three_point_pct':divide(c('tpm'),c('tpa')),'three_point_attempt_rate':divide(c('tpa'),fga),
      'opponent_three_point_pct':divide(c('d_tpm'),c('d_tpa')),
      'effective_fg_pct':divide(c('fgm')+.5*c('tpm'),fga),
      'opponent_effective_fg_pct':divide(c('d_fgm')+.5*c('d_tpm'),opp),
      'offensive_rebound_pct':divide(c('orb'),c('orb')+c('d_drb')),
      'defensive_rebound_pct':divide(c('drb'),c('drb')+c('d_orb')),
      'turnover_rate':divide(c('to'),fga+.44*c('fta')+c('to')),
      'forced_turnover_rate':divide(c('d_to'),opp+.44*c('d_fta')+c('d_to')),
      'free_throw_rate':divide(c('fta'),fga),'opponent_free_throw_rate':divide(c('d_fta'),opp)})
def main():
    p=argparse.ArgumentParser();p.add_argument('--season',type=int,default=2027);p.add_argument('--out',default='.');a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    df=fetch('ncaa_mbb_team_box',a.season,out)
    missing=set(['team','contest_id']+METRICS)-set(df.columns)
    if missing:raise ValueError(f'Team box missing columns: {sorted(missing)}')
    df=df[['team','contest_id']+METRICS].dropna(subset=['team','contest_id']).copy()
    df['contest_id']=df['contest_id'].astype(str).str.strip()
    for col in METRICS:df[col]=pd.to_numeric(df[col],errors='coerce')
    df=df.dropna(subset=METRICS)
    if df.duplicated(['contest_id','team']).any():raise ValueError('Duplicate team/game rows: stopped for safety')
    total=df.groupby('team',as_index=False)[METRICS].sum();games=df.groupby('team').size().rename('games').reset_index()
    total=total.merge(games,on='team',validate='one_to_one')
    season=factors(total,total.games,a.season);season['source']='SportsDataverse season aggregate (not pregame)';season['pregame_verified']='NO'
    dest=out/f'ncaa_season_four_factors_{a.season}.csv';season.sort_values('team').to_csv(dest,index=False)
    print(f'SAVED {len(season)} season team aggregates: {dest.resolve()}')
    schedule=fetch('ncaa_mbb_schedule',a.season,out)
    if not {'contest_id','game_date'}.issubset(schedule.columns):raise ValueError('Schedule lacks contest_id/game_date')
    dates=schedule[['contest_id','game_date']].copy();dates['contest_id']=dates.contest_id.astype(str).str.strip()
    dates['game_date']=pd.to_datetime(dates.game_date,errors='coerce')
    if dates.game_date.isna().any():raise ValueError('Invalid dates in schedule')
    conflicting=dates.groupby('contest_id').game_date.nunique()
    if (conflicting>1).any():raise ValueError('Conflicting schedule dates for same contest_id')
    dates=dates.drop_duplicates('contest_id')
    df=df.merge(dates,on='contest_id',how='left',validate='many_to_one')
    missing_dates=df.game_date.isna().sum()
    if missing_dates:
        print(f'WARNING: {missing_dates} team-game rows have no matching schedule date. Pregame CSV NOT created.')
        df.loc[df.game_date.isna(),['contest_id','team']].drop_duplicates().to_csv(out/'unmatched_ncaa_games.csv',index=False)
        return
    day=df.groupby(['team','game_date'],as_index=False)[METRICS].sum().sort_values(['team','game_date'])
    count=df.groupby(['team','game_date']).size().rename('day_games').reset_index();day=day.merge(count,on=['team','game_date'])
    grouped=day.groupby('team',sort=False)
    prior=day[['team','game_date']].copy()
    for col in METRICS:prior[col]=grouped[col].cumsum()-day[col]
    prior_games=grouped.day_games.cumsum()-day.day_games
    pre=factors(prior,prior_games,a.season,day.game_date.dt.strftime('%Y-%m-%d'))
    pre['source']='SportsDataverse team box joined to NCAA schedule; prior calendar-day games only'
    pre['pregame_verified']='DATE-MAPPED; verify schedule source and data publication timing'
    pre=pre.loc[pre.games>0].sort_values(['as_of_date','team'])
    dest2=out/f'ncaa_pregame_four_factors_{a.season}.csv';pre.to_csv(dest2,index=False)
    print(f'SAVED {len(pre)} date-mapped prior-day team snapshots: {dest2.resolve()}')
    print('NOTE: Date-mapped is not publication-time verified; do not automatically score historical picks.')
if __name__=='__main__':main()
