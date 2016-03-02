#!/bin/env python3

import ewebsockets
from ewebsockets import Frame, OpCode
from time import time
import maxthreads
from .forms import *
import logging
from .chat_room import *
from .database import *
from .client import Client
from .crypto import *

def str2hex(string):
    return ewebsockets.int2bytes(int(string, 16), int(len(string)/2))

class Chat:
    def __init__(self,
                 max_send_threads=10,
                 send_timeout=2):

        self.server = ewebsockets.Websocket(
            handle_new_connection=self.handle_new_connection,
            handle_websocket_frame=self.handle_incoming_frame,
            on_client_open=self.on_client_open,
            on_client_close=self.on_client_close
        )
        self.rooms = {}
        self.db = ChatDb()
        self.send_threads_limiter = maxthreads.MaxThreads(max_send_threads)
        self.send_timeout = send_timeout
        self.clients = {}

    def start(self):
        self.server.start()

    def stop(self):
        self.server.stop()

    def handle_request(self, client, msg):
        logging.debug('New request of type {} ({})'.format(msg['type'],
                                                           list(client_requests.keys())[list(client_requests.values()).index(msg['type'])]))
        if msg['type'] == client_requests['SINGLE_MESSAGE']:
            if client.logged_in:
                t = time()
                msg_id = self.db.insert('messages', {
                    'user': client.name,
                    'text': msg['text'],
                    'room_name': client.room_name,
                    'show': 1,
                    'time': t
                })
                self.rooms[client.room_name].broadcast_message(client.name, msg['text'], t, msg_id)
                return_value = True
            else:
                return_value = False

            client.send({
                    'type': client_requests['SINGLE_MESSAGE'],
                    'accepted': return_value
            })

        elif msg['type'] == client_requests['CHECK_USERNAME']:
            client.send({
                    'type': client_requests['CHECK_USERNAME'],
                    'available': self.db.check_existence('users', 'name', msg['name'])
            })
            return True
        elif msg['type'] == client_requests['CHECK_EMAIL']:
            client.send({
                    'type': client_requests['CHECK_EMAIL'],
                    'available': self.db.check_existence('users', 'email', msg['email'])
            })
            return True
        elif msg['type'] == client_requests['KEY_IV']:
            client.send_key()
            return True
        elif msg['type'] == client_requests['REGISTER']:
            email = decrypt(str2hex(msg['email']), client.key, client.iv)
            name = decrypt(str2hex(msg['name']), client.key, client.iv)
            password = decrypt(str2hex(msg['password']), client.key, client.iv)

            email_available = not self.db.check_existence('users', 'email', email)
            name_available = not self.db.check_existence('users', 'name', name)

            if email_available and name_available:
                self.db.insert('users', {
                    'name': name,
                    'email': email,
                    'password': password,
                    'joined': time(),
                    'last_online': time()
                })
                logging.debug('{}: Registered'.format(client.websocket.address))
                accepted = True
                client.logged_in = True
                client.name = name
            else:
                logging.debug('{}: registration denied'.format(client.websocket.address))
                accepted = False

            client.send({
                'type': client_requests['REGISTER'],
                'accepted': accepted,
                'name': name
            })


            return True
        elif msg['type'] == client_requests['LOGIN']:

            email = decrypt(str2hex(msg['email']), client.key, client.iv)
            password = decrypt(str2hex(msg['password']), client.key, client.iv)
            data = self.db.fetch('''SELECT name, password FROM users WHERE email="{}"'''.format(email))
            if data and data[1] == password:
                client.name = data[0]
                client.login(accept=True)
            else:
                client.login(accept=False)

            return True
        elif msg['type'] == client_requests['ENTER_ROOM']:
            room_name = msg['name']
            if room_name not in self.rooms:
                self.load_room(room_name)

            if client.room_name is not None:
                self.rooms[room_name].remove_client(client)
            client.room_name = room_name
            self.rooms[room_name].add_client(client)

            data = self.db.fetch('''SELECT id, user, text, time FROM messages WHERE room_name="{}"'''.format(room_name), all=True)
            if data is not None:
                length = len(data)
            else:
                length = 0
            messages = list(range(length))

            for i in range(length):
                messages[i] = {
                    'id': data[i][0],
                    'user': data[i][1],
                    'text': data[i][2],
                    'time': data[i][3]
                }
            client.send({
                'type': client_requests['ENTER_ROOM'],
                'messages': messages
            })

    def load_room(self, name):
        data = self.db.fetch('''SELECT id, name FROM rooms where name="{}"'''.format(name))
        if data is None:
            room_id = self.db.insert('rooms', {
                'name': name,
                'created': time()
            })
            logging.debug('Room "{}" created'.format(name))
        else:

            room_id = data[0]
        self.rooms[name] = ChatRoom(name, room_id)
        logging.debug('Room "{}" loaded'.format(name))

    def handle_incoming_frame(self, client, frame):
        if frame.opcode == OpCode.TEXT:
            try:
                msg = json.JSONDecoder().decode(frame.payload.decode('utf-8'))
                return self.handle_request(self.clients[client.address], msg)
            except json.JSONDecodeError:
                return False
        else:
            return False

    def handle_new_connection(self, client):
        return True

    def on_client_open(self, client):
        new_client = Client(
            name='temporaty_name',
            websocket=client,
            send_limiter=self.send_threads_limiter
        )
        self.clients[client.address] = new_client

    def on_client_close(self, client):

        client_obj = self.clients[client.address]
        name = client_obj.name
        self.rooms[client_obj.room_name].remove_client(client_obj)
        if len(self.rooms[client_obj.room_name].clients) == 0:
            del self.rooms[client_obj.room_name]
            logging.debug('Removing room "{}" from memory because no users are left in it'.format(client_obj.name))
        del self.clients[client.address]
        logging.debug('{}: Disconnected'.format(name))

    # def handle_incoming_frame(self, client, frame):
    #     if frame.opcode == OpCode.TEXT:
    #         client_obj = self.clients[client.address]
    #         data = json.JSONDecoder().decode(frame.payload.decode('utf-8'))
    #         if data['type'] == client_forms['SINGLE_MESSAGE']:
    #             if client_obj.logged_in:
    #                 msg_time = time()
    #                 msg_id = self.db.insert('messages',{
    #                     'user': client_obj.name,
    #                     'text': data['text'],
    #                     'room_id': client_obj.room_id,
    #                     'show': 1,
    #                     'time': msg_time
    #                 })
    #                 self.rooms[client_obj.room_id].broadcast({
    #                         'type': server_forms['SINGLE_MESSAGE'],
    #                         'user': client_obj.name,
    #                         'time': msg_time,
    #                         'text': data['text'],
    #                         'id': msg_id
    #                 })
    #         elif data['type'] == client_forms['LOGIN']:
    #             client_obj.login()
    #         elif data['type'] == client_forms['ENTER_ROOM']:
    #             room_name = data.room_id
    #             if room_name in self.rooms:
    #                 self.rooms[client_obj.room_name].remove_client(client_obj)
    #                 self.rooms[room_name].add_client(client_obj)
    #                 client_obj.room_name = room_name
    #
    #                 messages = self.db.fetch('''SELECT id, text, user from messages WHERE room''')
    #     return True
    #
    # def handle_new_connection(self, client):
    #
    #     return True
    #
    # def on_client_open(self, client):
    #     new_client = Client(
    #         name='temporaty_name',
    #         websocket=client,
    #         send_limiter=self.send_threads_limiter,
    #         room_id=0
    #     )
    #     self.rooms[0].add_client(new_client)
    #     self.clients[client.address] = new_client
    #     new_client.send_key()
    #
    #     self.db.fetch('''SELECT id, text, user, time FROM messages where room_id''')
    #     # encrypted = encrypt(b'Hello from server', key, iv)
    #     # data2 = data_frame(type=TYPE_SINGLE_MESSAGE,
    #     #                    user='Zaebos',
    #     #                    time=time(),
    #     #                    text=encrypted.hex(),
    #     #                    id=1,
    #     #                    room_id=0,
    #     #                    )
    #     # print(data2)
    #     #
    #     # data3 = {'type': TYPE_MASS_MESSAGE,
    #     #          'messages': [
    #     #              {
    #     #                  'type': TYPE_SINGLE_MESSAGE,
    #     #                  'user': 'Zaebos',
    #     #                  'time': time(),
    #     #                  'text': encrypted.hex(),
    #     #                  'id': 1,
    #     #                  'room_id': 0
    #     #              },
    #     #              {
    #     #                  'type': TYPE_SINGLE_MESSAGE,
    #     #                  'user': 'Zaebos',
    #     #                  'time': time(),
    #     #                  'text': encrypted.hex(),
    #     #                  'id': 1,
    #     #                  'room_id': 0
    #     #              }
    #     #          ]}
    #     # new_client.send_data(data2)
    #     # new_client.send_data(data_frame(**data3))
    #
    # def add_room(self, name):
    #     room_id = self.db.insert('rooms', {'name': name, 'created': time()})
    #     self.open_room(name, room_id)
    #
    # def open_room(self, name, room_id):
    #     self.rooms[room_id] = ChatRoom(name, room_id)
    #
    # def load_rooms(self):
    #     db = self.db.connect()
    #     cursor = db.cursor()
    #     cursor.execute('''SELECT id, name FROM rooms''')
    #     all_rooms = cursor.fetchall()
    #     for room in all_rooms:
    #         self.open_room(room_id=room[0], name=room[1])
