import collections
import datetime
import enum

import tornadis
import tornado

_channels = collections.defaultdict(list)
_data = {}

class RedisCommands(enum.Enum):
    PUBLISH = 'publish'
    GET = 'get'
    SET = 'set'
    SETEX = 'setex'
    HMSET = 'hmset'
    HGET = 'hget'

class MockClient(tornadis.Client):
    channels = _channels
    data = _data

    @tornado.gen.coroutine
    def call(self, *args, **kwargs):
        command = RedisCommands(args[0].lower())

        if command == RedisCommands.PUBLISH:
            channel = self.channels[args[1]]
            message = args[2]

            for client in channel:
                client._reply_list.append(message)

            raise tornado.gen.Return(len(channel))
        elif command == RedisCommands.GET:
            key = args[1]
            if key not in self.data:
                raise tornado.gen.Return(None)

            val = self.data[key]
            if val[0] == RedisCommands.SETEX and datetime.datetime.utcnow() < val[2]:
                del self.data[key]
                raise tornado.gen.Return(None)

            return val[1]
        elif command == RedisCommands.SETEX:
            key = args[1]
            ttl = datetime.datetime.utcnow() + datetime.timedelta(seconds=args[2])
            data = args[3]

            self.data[key] = (RedisCommands.SETEX, data, ttl)
        elif command == RedisCommands.SET:
            key = args[1]
            data = args[3]

            self.data[key] = (RedisCommands.SET, data)
        elif command == RedisCommands.HMSET:
            arg_len = len(args) - 2
            if arg_len % 2 or arg_len < 1:
                raise ValueError('Invalid parameters.')

            dict_args = zip(*[iter(args[2:])]*2)
            new_dict = {}
            for key, val in dict_args:
                new_dict[key] = val

            key = args[1]
            self.data[key] = (RedisCommands.HMSET, new_dict)
        elif command == RedisCommands.HGET:
            if len(args) != 3:
                raise ValueError('Invalid parameters.')

            key = args[1]
            field = args[2]
            return self.data[key][1][field]

    def is_connected(self):
        return True

    def clear_mock_redis(self):
        self.channels.clear()

class MockPubSubClient(tornadis.PubSubClient, MockClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reply_list = []

    @tornado.gen.coroutine
    def pubsub_subscribe(self, *args):
        for channel in args:
            self.channels[channel].append(self)

        raise tornado.gen.Return(len(args))

    @tornado.gen.coroutine
    def pubsub_unsubscribe(self, *args):
        for channel in args:
            self.channels[channel].remove(self)

        raise tornado.gen.Return(len(args))

    @tornado.gen.coroutine
    def pubsub_pop_message(self, *args, **kwargs):
        reply = None

        try:
            reply = self._reply_list.pop(0)
            raise tornado.gen.Return(reply)
        except IndexError:
            pass

        yield self._condition.wait()
        try:
            reply = self._reply_list.pop(0)
        except IndexError:
            pass

        raise tornado.gen.Return(reply)
