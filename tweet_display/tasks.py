from __future__ import absolute_import, unicode_literals
from celery import shared_task
from tzwhere import tzwhere
from .models import Graph

import tempfile
import requests
import zipfile
import json
import datetime
import pytz
import gender_guesser.detector as gender
import pandas as pd
import io

gender_guesser = gender.Detector(case_sensitive=False)
tzwhere_ = tzwhere.tzwhere()

### READ JSON FILES FROM TWITTER ARCHIVE!

def check_hashtag(single_tweet):
    '''check whether tweet has any hashtags'''
    return len(single_tweet['entities']['hashtags']) > 0

def check_media(single_tweet):
    '''check whether tweet has any media attached'''
    return len(single_tweet['entities']['media' ]) > 0

def check_url(single_tweet):
    '''check whether tweet has any urls attached'''
    return len(single_tweet['entities']['urls']) > 0

def check_retweet(single_tweet):
    '''
    check whether tweet is a RT. If yes:
    return name & user name of the RT'd user.
    otherwise just return nones
    '''
    if 'retweeted_status' in single_tweet.keys():
        return (single_tweet['retweeted_status']['user']['screen_name'],
                single_tweet['retweeted_status']['user']['name'])
    else:
        return (None,None)

def check_coordinates(single_tweet):
    '''
    check whether tweet has coordinates attached.
    if yes return the coordinates
    otherwise just return nones
    '''
    if 'coordinates' in single_tweet['geo'].keys():
        return (single_tweet['geo']['coordinates'][0],
                single_tweet['geo']['coordinates'][1])
    else:
        return (None,None)

def check_reply_to(single_tweet):
    '''
    check whether tweet is a reply. If yes:
    return name & user name of the user that's replied to.
    otherwise just return nones
    '''
    if 'in_reply_to_screen_name' in single_tweet.keys():
        name = None
        for user in single_tweet['entities']['user_mentions']:
            if user['screen_name'] == single_tweet['in_reply_to_screen_name']:
                name = user['name']
                break
        return (single_tweet['in_reply_to_screen_name'],name)
    else:
        return (None,None)

def convert_time(coordinates,time_utc):
    '''
    Does this tweet have a geo location? if yes
    we can easily convert the UTC timestamp to true local time!
    otherwise return nones
    '''
    if coordinates[0] and coordinates[1]:
        timezone_str = tzwhere_.tzNameAt(coordinates[0],coordinates[1])
        if timezone_str:
            timezone = pytz.timezone(timezone_str)
            time_obj_local = datetime.datetime.astimezone(time_utc,timezone)
            return time_obj_local

def create_dataframe(tweets):
    '''
    create a pandas dataframe from our tweet jsons
    '''

    # initalize empty lists
    utc_time = []
    longitude = []
    latitude = []
    local_time = []
    hashtag = []
    media = []
    url = []
    retweet_user_name = []
    retweet_name = []
    reply_user_name = []
    reply_name = []
    text = []
    # iterate over all tweets and extract data
    for single_tweet in tweets:
        utc_time.append(datetime.datetime.strptime(single_tweet['created_at'],'%Y-%m-%d %H:%M:%S %z'))
        coordinates = check_coordinates(single_tweet)
        latitude.append(coordinates[0])
        longitude.append(coordinates[1])
        local_time.append(convert_time(coordinates,datetime.datetime.strptime(single_tweet['created_at'],'%Y-%m-%d %H:%M:%S %z')))
        hashtag.append(check_hashtag(single_tweet))
        media.append(check_media(single_tweet))
        url.append(check_url(single_tweet))
        retweet = check_retweet(single_tweet)
        retweet_user_name.append(retweet[0])
        retweet_name.append(retweet[1])
        reply = check_reply_to(single_tweet)
        reply_user_name.append(reply[0])
        reply_name.append(reply[1])
        text.append(single_tweet['text'])
    # convert the whole shebang into a pandas dataframe
    dataframe = pd.DataFrame(data= {
                    'utc_time' : utc_time,
                    'local_time' : local_time,
                    'latitude' : latitude,
                    'longitude' : longitude,
                    'hashtag' : hashtag,
                    'media' : media,
                    'url' : url,
                    'retweet_user_name' : retweet_user_name,
                    'retweet_name' : retweet_name,
                    'reply_user_name' : reply_user_name,
                    'reply_name' : reply_name,
                    'text' : text
    })
    return dataframe

def read_files(zip_url):
    tf = tempfile.NamedTemporaryFile()
    tf.write(requests.get(zip_url).content)
    zf = zipfile.ZipFile(tf.name)
    with zf.open('data/js/tweet_index.js','r') as f:
        f  = io.TextIOWrapper(f)
        d = f.readlines()[1:]
        d = "[{" + "".join(d)
        json_files = json.loads(d)
    data_frames = []
    for single_file in json_files:
        with zf.open(single_file['file_name']) as f:
            f  = io.TextIOWrapper(f)
            d = f.readlines()[1:]
            d = "".join(d)
            tweets = json.loads(d)
            df_tweets = create_dataframe(tweets)
            data_frames.append(df_tweets)
    return data_frames

def create_main_dataframe(zip_url='http://ruleofthirds.de/test_archive.zip'):
    dataframes = read_files(zip_url)
    dataframe = pd.concat(dataframes)
    dataframe = dataframe.sort_values('utc_time',ascending=False)
    dataframe = dataframe.set_index('utc_time')
    dataframe = dataframe.replace(to_replace={
                                    'url': {False: None},
                                    'hashtag': {False: None},
                                    'media': {False: None}
                                    })
    return dataframe

### GENERATE JSON FOR GRAPHING ON THE WEB

def create_all_tweets(dataframe,rolling_frame='180d'):
    dataframe_grouped = dataframe.groupby(dataframe.index.date).count()
    dataframe_grouped.index = pd.to_datetime(dataframe_grouped.index)
    dataframe_mean_week = dataframe_grouped.rolling(rolling_frame).mean()

def create_hourly_stats(dataframe):
    get_hour = lambda x: x.hour
    get_weekday = lambda x: x.weekday()

    local_times = dataframe.copy()
    local_times = local_times.loc[dataframe['local_time'].notnull()]

    local_times['weekday'] = local_times['local_time'].apply(get_weekday)
    local_times['hour'] = local_times['local_time'].apply(get_hour)


    local_times = local_times.replace(to_replace={'weekday':
                                                    {0:'Weekday',
                                                     1:'Weekday',
                                                     2:'Weekday',
                                                     3:'Weekday',
                                                     4:'Weekday',
                                                     5:'Weekend',
                                                     6:'Weekend',
                                                    }
                                       })

    local_times = local_times.groupby([local_times['hour'],local_times['weekday']]).size().reset_index()
    local_times['values'] = local_times[0]
    local_times = local_times.set_index(local_times['hour'])

    return local_times.pivot(columns='weekday', values='values').reset_index()

def predict_gender(dataframe,column_name,rolling_frame='180d'):
    '''
    take full dataframe w/ tweets and extract
    gender for a name-column where applicable
    returns two-column df w/ timestamp & gender
    '''
    splitter = lambda x: x.split()[0]
    gender_column = dataframe.loc[dataframe[column_name].notnull()][column_name].apply(
        splitter).apply(
        gender_guesser.get_gender)

    gender_dataframe = pd.DataFrame(data = {
                    'time' : list(gender_column.index),
                    'gender' : list(gender_column)
                    })

    gender_dataframe = gender_dataframe.set_index('time')
    gender_dataframe_tab = gender_dataframe.groupby([gender_dataframe.index.date,gender_dataframe['gender']]).size().reset_index()
    gender_dataframe_tab['date'] = gender_dataframe_tab['level_0']
    gender_dataframe_tab['count'] = gender_dataframe_tab[0]
    gender_dataframe_tab = gender_dataframe_tab.drop([0,'level_0'],axis=1)
    gender_dataframe_tab = gender_dataframe_tab.set_index('date')
    gender_dataframe_tab.index = pd.to_datetime(gender_dataframe_tab.index)
    gdf_pivot = gender_dataframe_tab.pivot(columns='gender', values='count')
    gdf_pivot = gdf_pivot.rolling(rolling_frame).mean()
    gdf_pivot = gdf_pivot.reset_index()
    gdf_pivot['date'] = gdf_pivot['date'].astype(str)
    gdf_pivot = gdf_pivot.drop(['mostly_male','mostly_female','andy','unknown'],axis=1)
    return gdf_pivot

### DUMP JSON FOR GRAPHING
def write_graph(dataframe, graph_type, graph_desc):
    json_object = dataframe.to_json(orient='records')
    graph = Graph.objects.create()
    try:
        graph.graph_type = graph_type
        graph.graph_description = graph_desc
        graph.graph_data = str(json_object)
        graph.save()
    except:
        graph.delete()


#def __main__():
#    dataframe = create_main_dataframe()
#    retweet_gender = predict_gender(dataframe,'retweet_name','180d')
#    write_json_for_graph(retweet_gender,'gender_rt','retweets by gender')
    #reply_gender = predict_gender(dataframe,'reply_name','180d')
    #write_json_for_graph(retweet_gender,'gender_reply.json')

@shared_task
def xsum(numbers):
    return sum(numbers)

@shared_task
def import_data(url='http://ruleofthirds.de/test_archive.zip'):
    dataframe = create_main_dataframe(url)
    retweet_gender = predict_gender(dataframe,'retweet_name','180d')
    write_graph(retweet_gender,'gender_rt','retweets by gender')
    reply_gender = predict_gender(dataframe,'reply_name','180d')
    write_graph(reply_gender,'gender_reply','replies by gender')

#if __name__ == "__main__":
#    main()
