"""Server-only account recovery. Passwords are read interactively, never command arguments."""
import argparse
import getpass
import secrets

from . import store
from .main import password_hash


def main():
    parser = argparse.ArgumentParser(description='共享库账号密码恢复；需要服务器访问权限')
    parser.add_argument('username')
    args = parser.parse_args()
    password = getpass.getpass('新密码（至少 10 位）: ')
    if not 10 <= len(password) <= 128 or password != getpass.getpass('再次输入新密码: '):
        raise SystemExit('密码长度不符或两次输入不一致。')
    store.initialize()
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        user = con.execute('SELECT id FROM users WHERE username=?', (args.username.lower(),)).fetchone()
        if not user:
            raise SystemExit('用户名不存在。')
        salt = secrets.token_hex(16)
        con.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt,password_hash(password,salt),user['id']))
        con.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
    print('密码已更新，原有登录会话已失效。')


if __name__ == '__main__':
    main()
