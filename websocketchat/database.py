#!/bin/env python3

import sqlite3
from time import time
import logging
# from .chat_server import random_str
from .crypto import hash
import random, string
import json

def random_str(n):
    return ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(n))

class ChatDb:
    def __init__(self):
        self.name = 'chat.db'
        self.db = sqlite3.connect('chat.db', check_same_thread=False)
        # self.cursor = self.db.cursor()
        self.tables = {'users': {'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                                 'name': 'TEXT NOT NULL',
                                 'email': 'TEXT NOT NULL',
                                 'password': 'TEXT NOT NULL',
                                 'salt': 'TEXT NOT NULL',
                                 'registered': 'INTEGER NOT NULL',
                                 'last_online': 'INTEGER NOT NULL',
                                 'tokens': 'TEXT NOT NULL',
                                 'verification_code': 'TEXT'},

                       'messages': {'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                                    'user': 'TEXT NOT NULL',
                                    'text': 'TEXT NOT NULL',
                                    'room_name': 'TEXT NOT NULL',
                                    'show': 'INTEGER NOT NULL',
                                    'time': 'INTEGER NOT NULL'},
                       'rooms': {'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                                 'name': 'TEXT NOT NULL',
                                 'created': 'INTEGER NOT NULL'}

                       }
        self.create_tables()

    def connect(self):
        # return sqlite3.connect(self.name)
        return self.db

    def close(self):
        self.db.close()

    def execute(self, command, entries=(), commit=False, fetch=None):
        # db = sqlite3.connect(self.name)
        cursor = self.db.cursor()
        row_id = None

        cursor.execute(command, entries)

        if commit:
            row_id = cursor.lastrowid
            self.db.commit()
            return row_id

        if fetch == 'one':
            return cursor.fetchone()
        elif fetch == 'all':
            return cursor.fetchall()

    def insert(self, table, entries):
        # db = self.connect()
        # cursor = db.cursor()
        #
        command = '''INSERT INTO {}({}) VALUES({}?)'''.format(table,
                                                              ', '.join(entries.keys()),
                                                              '?,'*(len(entries)-1))

        entries = tuple(entries.values())
        return self.execute(command, entries, commit=True)

        # cursor.execute(command, entries)
        # row_id = cursor.lastrowid
        # db.commit()
        # # db.close()
        # logging.debug('Inserted {} into database table {}'.format(entries, table))
        # return row_id

    def create_table(self, name, entries):
        columns = list(entries.items())
        for i in range(len(columns)):
            columns[i] = ' '.join(columns[i])
        columns = ', '.join(columns)
        self.execute('''CREATE TABLE IF NOT EXISTS {}({})'''.format(name, columns), commit=True)

    def create_tables(self):
        for table in self.tables:
            self.create_table(table, self.tables[table])

    def check_existence(self, table, column, entry):
        command = '''SELECT id FROM {} WHERE {}=?'''.format(table, column)
        # db = self.connect()
        # cursor = db.cursor()
        # if type(entry) == str:
        #     entry = '"' + entry + '"'
        # else:
        #     entry = str(entry)
        # cursor.execute('''SELECT id FROM {} WHERE {}={}'''.format(table, column, entry))
        # print('''SELECT EXISTS(SELECT 1 FROM {} WHERE {}={})'''.format(table,
        #                                                                         column,
        #                                                                         entry))
        # # cursor.execute('''SELECT EXISTS(SELECT 1 FROM {} WHERE {}={})'''.format(table,
        #                                                                         column,
        #                                                                         entry))
        # db.close()
        data = self.execute(command, (entry, ), fetch='one')
        if data is None:
            return False
        else:
            return True

    # def fetch(self, command, all=False):
    #     db = self.connect()
    #     cursor = db.cursor()
    #     cursor.execute(command)
    #
    #     if all:
    #         data = cursor.fetchall()
    #     else:
    #         data = cursor.fetchone()
    #     # db.close()
    #     return data

    def add_message(self, client, text, show=1):
        t = time()

        id = self.insert('messages', {
                'user': client.name,
                'text': text,
                'room_name': client.room_name,
                'show': show,
                'time': t})

        return id, t

    def get_messages(self, room_name, last_id, latest):
        messages = self.execute('''SELECT id, time, user, text FROM messages WHERE room_name = ? AND id > ?''',
                            (room_name, last_id), fetch='all')
        length = len(messages)
        if length > latest:
            messages = messages[length-latest:]

        return messages

    def validate_login(self, email, password, request_token):
        if request_token:
            command = '''SELECT id, name, password, salt, verification_code, tokens FROM users WHERE email = ?'''
        else:
            command = '''SELECT id, name, password, salt, verification_code FROM users WHERE email = ?'''

        data = self.execute(command, (email,), fetch='one')

        if data is None:
            # No user with that email was found
            return

        if request_token:
            user_id, name, stored_password, salt, verification_code, tokens = data
        else:
            user_id, name, stored_password, salt, verification_code = data

        salted_password = hash(password + salt)
        if salted_password == stored_password:
            # User login accepted
            request_email_verification = verification_code is not None

            token = ''
            if request_token:
                tokens = json.JSONDecoder().decode(tokens)
                token = random_str(32)
                tokens.append(token)
                if len(tokens) > 10:
                    # Maximum saved tokens set to 10
                    tokens = tokens[1:]

                tokens = json.JSONEncoder().encode(tokens)
                command = '''UPDATE users SET tokens = ? WHERE Id = ?'''
                self.execute(command, (tokens, user_id), commit=True)

            return user_id, name, request_email_verification, token
        else:
            return

    def validate_auto_login(self, client, email, token):
            data = self.execute(
                '''SELECT id, name, tokens, verification_code FROM users WHERE email = ?''',
                (email,), fetch='one'
            )
            if data is None:
                return

            user_id, name, tokens, verification_code = data
            tokens = json.JSONDecoder().decode(tokens)

            if token in tokens:
                tokens.remove(token)
                new_token = random_str(32)
                tokens.append(new_token)

                self.execute('''UPDATE users SET tokens=? WHERE Id = ?''',
                                    (json.JSONEncoder().encode(tokens), user_id),
                             commit=True)
                request_email_verification = verification_code is not None

                return user_id, name, new_token, request_email_verification
            else:
                logging.debug('{}: Deleting tokens'.format(client.address()))
                tokens = []
                self.execute('''UPDATE users SET tokens=? WHERE email = ?''',
                                    (json.JSONEncoder().encode(tokens), email),
                             commit=True)

                return

    def new_user(self, email, name, password):
        salt = random_str(32)
        salted_password = hash(password + salt)
        verification_code = random_str(7)
        user_id = self.insert('users', {
            'name': name,
            'email': email,
            'password': salted_password,
            'salt': salt,
            'registered': time(),
            'verification_code': verification_code,
            'last_online': time(),
            'tokens': '[]'
        })
        return user_id, verification_code

    def new_token(self, client):
        tokens, = self.execute('''SELECT tokens FROM users WHERE id = ?''', (client.id,), fetch='one')
        tokens = json.JSONDecoder().decode(tokens)
        token = random_str(32)
        tokens.append(token)
        if len(tokens) > 10:
            logging.debug('{}: too many tokens removing oldest'.format(client.address()))
            tokens = tokens[len(tokens)-10:]

        self.execute('''UPDATE users SET tokens=? WHERE Id=?''',
                     (json.JSONEncoder().encode(tokens), client.id),
                     commit=True)

        return token

    def remove_token(self, client, token):
        tokens, = self.execute('''SELECT tokens FROM users WHERE id = ?''', (client.id,), fetch='one')
        tokens = json.JSONDecoder().decode(tokens)

        if token in tokens:
            tokens.remove(token)

        self.execute('''UPDATE users SET tokens=? WHERE Id=?''',
                     (json.JSONEncoder().encode(tokens), client.id),
                     commit=True)

        return token

    def get_verification_code(self, user_id):
        command = '''SELECT verification_code FROM users WHERE id = ?'''
        verification_code, = self.execute(command, (user_id, ), fetch='one')
        return verification_code

    def remove_verification_code(self, user_id):
        command = '''UPDATE users SET verification_code = NULL WHERE id = ?'''
        self.execute(command, (user_id, ), commit=True)

    def get_new_verification_code(self, user_id):
        verification_code = self.get_verification_code(user_id)
        if verification_code is None:
            return

        new_verification_code = random_str(7)
        command = '''UPDATE users SET verification_code = ? WHERE id = ?'''

        self.execute(command, (new_verification_code, user_id))

        return new_verification_code


















