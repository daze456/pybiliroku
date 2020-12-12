import json
import os
import math
from datetime import datetime
from urllib import parse
import hashlib
import requests
import cipher
from concurrent.futures import ThreadPoolExecutor, as_completed

APPKEY = 'aae92bc66f3edfab'
APPSECRET = 'af125a0d5279fd576c1b4418a3e8276d'

# upload chunk size = 2MB
CHUNK_SIZE = 2 * 1024 * 1024


def get_key():
    """
    get public key, hash and session id for login.

    Returns:
        hash: salt for password encryption.
        pubkey: rsa public key for password encryption.
        sid: session id.
    """
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': "application/json, text/javascript, */*; q=0.01"
    }
    post_data = {
        'appkey': APPKEY,
        'platform': "pc",
        'ts': str(int(datetime.now().timestamp()))
    }
    post_data['sign'] = cipher.sign_dict(post_data, APPSECRET)

    r = requests.post(
        "https://passport.bilibili.com/api/oauth2/getKey",
        headers=headers,
        data=post_data
    )
    r_data = r.json()['data']
    return r_data['hash'], r_data['key'], r.cookies['sid']


def get_capcha(sid, file_name=None):
    headers = {
        'User-Agent': '',
        'Accept-Encoding': 'gzip,deflate',
    }

    params = {
        'appkey': APPKEY,
        'platform': 'pc',
        'ts': str(int(datetime.now().timestamp()))
    }
    params['sign'] = cipher.sign_dict(params, APPSECRET)

    r = requests.get(
        "https://passport.bilibili.com/captcha",
        headers=headers,
        params=params,
        cookies={
            'sid': sid
        }
    )

    print(r.status_code)

    capcha_data = r.content

    if file_name is not None:
        with open(file_name, 'wb+') as f:
            f.write(capcha_data)

    return r.cookies['JSESSIONID'], capcha_data
    

class VideoPart:
    """
    Video Part of a post.
    每个对象代表一个分P

    Attributes:
        path: file path in local file system.
        title: title of the video part.
        desc: description of the video part.
        server_file_name: file name in bilibili server. generated by pre-upload API.
    """
    def __init__(self, path, title='', desc='', server_file_name=None):
        self.path = path
        self.title = title
        self.desc = desc
        self.server_file_name = server_file_name

        file_size = os.path.getsize(path)
        chunk_total_num = int(math.ceil(file_size / CHUNK_SIZE))
        self.progress = (0, chunk_total_num)

    def __repr__(self):
        return '<{clazz}, path: {path}, title: {title}, desc: {desc}, server_file_name:{server_file_name}>'\
            .format(clazz=self.__class__.__name__,
                    path=self.path,
                    title=self.title,
                    desc=self.desc,
                    server_file_name=self.server_file_name)


class BilibiliUploader():
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.sid = None
        self.mid = None
        self.parts = None

    def login(self, username, password):
        """
        bilibili login.
        Args:
            username: plain text username for bilibili.
            password: plain text password for bilibili.
        """
        hash, pubkey, sid = get_key()

        encrypted_password = cipher.encrypt_login_password(password, hash, pubkey)
        url_encoded_username = parse.quote_plus(username)
        url_encoded_password = parse.quote_plus(encrypted_password)

        post_data = {
            'appkey': APPKEY,
            'password': url_encoded_password,
            'platform': "pc",
            'ts': str(int(datetime.now().timestamp())),
            'username': url_encoded_username
        }

        post_data['sign'] = cipher.sign_dict(post_data, APPSECRET)
        # avoid multiple url parse
        post_data['username'] = username
        post_data['password'] = encrypted_password

        headers = {
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'User-Agent': '',
            'Accept-Encoding': 'gzip,deflate',
        }

        r = requests.post(
            "https://passport.bilibili.com/api/oauth2/login",
            headers=headers,
            data=post_data,
            cookies={
                'sid': sid
            }
        )
        login_data = r.json()['data']
        
        self.access_token = login_data['access_token']
        self.refresh_token = login_data['refresh_token']
        self.sid = sid
        self.mid = login_data['mid']

    def login_by_access_token(self, access_token, refresh_token=None):
        """
        bilibili access token login.
        Args:
            access_token: Bilibili access token got by previous username/password login.
        """
        self.access_token = access_token
        self.refresh_token = refresh_token

        headers = {
            'Connection': 'keep-alive',
            'Accept-Encoding': 'gzip,deflate',
            'Host': 'passport.bilibili.com',
            'User-Agent': '',
        }

        login_params = {
            'appkey': APPKEY,
            'access_token': access_token,
            'platform': "pc",
            'ts': str(int(datetime.now().timestamp())),
        }
        login_params['sign'] = cipher.sign_dict(login_params, APPSECRET)

        r = requests.get(
            url="https://passport.bilibili.com/api/oauth2/info",
            headers=headers,
            params=login_params
        )

        login_data = r.json()['data']

        self.sid = r.cookies['sid']
        self.mid = login_data['mid']

    def login_by_access_token_file(self, file_name):
        with open(file_name, "r") as f:
            login_data = json.loads(f.read())
        self.access_token = login_data["access_token"]
        self.refresh_token = login_data["refresh_token"]
        self.login_by_access_token(self.access_token, self.refresh_token)

    def save_login_data(self, file_name=None):
        login_data = json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token
            }
        )
        try:
            with open(file_name, "w+") as f:
                f.write(login_data)
        finally:
            return login_data

    def upload_cover(self, cover_file_path):
        with open(cover_file_path, "rb") as f:
            cover_pic = f.read()

        headers = {
            'Connection': 'keep-alive',
            'Host': 'member.bilibili.com',
            'Accept-Encoding': 'gzip,deflate',
            'User-Agent': '',
        }

        params = {
            "access_key": self.access_token,
        }

        params["sign"] = cipher.sign_dict(params, APPSECRET)

        files = {
            'file': ("cover.png", cover_pic, "Content-Type: image/png"),
        }

        r = requests.post(
            "http://member.bilibili.com/x/vu/client/cover/up",
            headers=headers,
            params=params,
            files=files,
            cookies={
                'sid': self.sid
            },
            verify=False,
        )

        return r.json()["data"]["url"]

    def upload_video_part(self, video_part: VideoPart, max_retry=5):
        """
        upload a video file.
        Args:
            access_token: access token generated by login api.
            sid: session id.
            mid: member id.
            video_part: local video file data.
            max_retry: max retry number for each chunk.

        Returns:
            status: success or fail.
            server_file_name: server file name by pre_upload api.
        """
        headers = {
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'User-Agent': '',
            'Accept-Encoding': 'gzip,deflate',
        }

        r = requests.get(
            "http://member.bilibili.com/preupload?access_key={}&mid={}&profile=ugcfr%2Fpc3".format(self.access_token, self.mid),
            headers=headers,
            cookies={
                'sid': self.sid
            },
            verify=False,
        )

        pre_upload_data = r.json()
        upload_url = pre_upload_data['url']
        complete_upload_url = pre_upload_data['complete']
        server_file_name = pre_upload_data['filename']
        local_file_name = video_part.path
        print(local_file_name, upload_url)

        file_size = os.path.getsize(local_file_name)
        chunk_total_num = int(math.ceil(file_size / CHUNK_SIZE))
        file_hash = hashlib.md5()

        def upload_chunk(chunk_data, chunk_id):
            video_part.progress = (chunk_id + 1, chunk_total_num)
            files = {
                'version': (None, '2.0.0.1054'),
                'filesize': (None, CHUNK_SIZE),
                'chunk': (None, chunk_id),
                'chunks': (None, chunk_total_num),
                'md5': (None, cipher.md5_bytes(chunk_data)),
                'file': (os.path.basename(local_file_name), chunk_data, 'application/octet-stream')
            }

            r = requests.post(
                url=upload_url,
                files=files,
                cookies={
                    'PHPSESSID': server_file_name
                },
            )
            #print(r.status_code, r.content)

            if not (r.status_code == 200 and r.json()['OK'] == 1):
                raise RuntimeError(r.status_code + " " + r.content.decode())

            # print progress
            for p in self.parts:
                width = 10
                nhashes = math.floor(p.progress[0]/p.progress[1]*width)
                print(f"[{'#'*nhashes + ' '*(width - nhashes)}] {p.progress[0]}/{p.progress[1]}: {p.title}")

        with open(local_file_name, 'rb') as f:
            for chunk_id in range(0, chunk_total_num):
                chunk_data = f.read(CHUNK_SIZE)

                for r in range(max_retry):
                    try: 
                        upload_chunk(chunk_data, chunk_id)
                        break
                    except RuntimeError as err:
                        if r >= max_retry - 1:
                            raise
                        print(local_file_name, str(err), "retry,", r)

                file_hash.update(chunk_data)
        #print(file_hash.hexdigest())

        # complete upload
        post_data = {
            'chunks': chunk_total_num,
            'filesize': file_size,
            'md5': file_hash.hexdigest(),
            'name': os.path.basename(local_file_name),
            'version': '2.0.0.1054',
        }

        r = requests.post(
            url=complete_upload_url,
            data=post_data,
            headers=headers,
        )
        if not (r.status_code == 200 and r.json()['OK'] == 1):
            raise RuntimeError(r.status_code + " " + r.content.decode())
        print(video_part.title, "complete", r.status_code, r.content.decode())

        video_part.server_file_name = server_file_name

        return True

    def upload(self,
               parts,
               copyright: int,
               title: str,
               tid: int,
               tag: str,
               desc: str,
               source: str = '',
               cover: str = '',
               no_reprint: int = 0,
               open_elec: int = 1,
               max_retry: int = 5,
               thread_pool_workers: int = 1):

        if not isinstance(parts, list):
            parts = [parts]

        self.parts = parts

        with ThreadPoolExecutor(max_workers=thread_pool_workers) as tpe:
            t_list = []
            for video_part in parts:
                print("upload {} added in pool".format(video_part.title))
                t_obj = tpe.submit(self.upload_video_part, video_part, max_retry)
                t_obj.video_part = video_part
                t_list.append(t_obj)

            for t_obj in as_completed(t_list):
                print("video part {} finished, status: {}".format(t_obj.video_part.title, t_obj.result()))

        # cover
        if os.path.isfile(cover):
            try:
                cover = self.upload_cover(cover)
            except:
                cover = ''
        else:
            cover = ''

        # submit
        headers = {
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'User-Agent': '',
        }
        post_data = {
            'build': 1054,
            'copyright': copyright,
            'cover': cover,
            'desc': desc,
            'no_reprint': no_reprint,
            'open_elec': open_elec,
            'source': source,
            'tag': tag,
            'tid': tid,
            'title': title,
            'videos': []
        }
        for video_part in parts:
            post_data['videos'].append({
                "desc": video_part.desc,
                "filename": video_part.server_file_name,
                "title": video_part.title
            })

        params = {
            'access_key': self.access_token,
        }
        params['sign'] = cipher.sign_dict(params, APPSECRET)
        r = requests.post(
            url="http://member.bilibili.com/x/vu/client/add",
            params=params,
            headers=headers,
            verify=False,
            cookies={
                'sid': self.sid
            },
            json=post_data,
        )
        if not (r.status_code == 200 and r.json()['code'] == 0):
            raise RuntimeError(r.status_code + " " + r.content.decode())

        print("submit", r.status_code, r.content.decode())

        data = r.json()["data"]
        return data["aid"], data["bvid"]
