import socket
import threading
import Queue
import httplib
import random

class SockOperImpl:
    def __init__(self, recvSize = 65536):
        self.recvSize = recvSize
    def connect(self, remoteHost, remotePort):
        self.socket = socket.socket()
        self.socket.connect((remoteHost, remotePort))
    def send(self, content):
        self.socket.send(content)
    def recv(self):
        return self.socket.recv(self.recvSize)
    def close(self):
        self.socket.close()

class StringStream:
    def __init__(self, string = ''):
        self.string = string
    def read(self, bytesCount):
        if len(self.string) == 0:
            raise EOFError()
        content = self.string[ : bytesCount]
        self.string = self.string[bytesCount : ]
        return content
    def write(self, content):
        self.string += content
    def __str__(self):
        return self.string

class SocketStream:
    def __init__(self, socket):
        self.socket = socket
    def read(self, bytesCount):
        return self.socket.recv(bytesCount)
    def write(self, content):
        self.socket.sendall(content)

class Packer:
    def __init__(self, outStream = StringStream()):
        self.outStream = outStream
    def packNumber(self, number, bytesCount):
        for i in xrange(0, bytesCount):
            self.outStream.write(chr((number >> ((bytesCount - 1 - i) * 8)) & 0xff))
    def pack(self, content, lengthBytes = 3):
        self.packNumber(len(content), lengthBytes)
        self.outStream.write(content)

class Unpacker:
    def __init__(self, inStream = StringStream()):
        self.inStream = inStream
    def readFully(self, bytesCount):
        remains = bytesCount
        content = ''
        while remains != 0:
            read = self.inStream.read(remains)
            content += read
            remains -= len(read)
        return content
    def unpackNumber(self, bytesCount):
        number = 0
        for i in xrange(0, bytesCount):
            number |= ord(self.inStream.read(1)) << (i * 8)
        return number
    def unpack(self, lengthBytes = 3):
        length = self.UnpackNumber(lengthBytes)
        return self.readFully(length)

class SockOperCmd:
    CONNECT_CMD = 0
    SEND_CMD = 1
    RECV_CMD = 2
    CLOSE_CMD = 3

class SockReqOperPacker:
    def __init__(self, session):
        self.session = session
    def pack(self, packet):
        packer = Packer()
        packer.pack(packed)
        return str(packer)
    def connect(self, remoteHost, remotePort):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.CONNECT_CMD, 1)
        packer.pack(remoteHost, 1)
        packer.packetNumber(remotePort, 2)
        return self.pack(str(packer))
    def send(self, content):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.SEND_CMD, 1)
        packer.pack(self.session)
        packer.pack(content)
        return self.pack(str(packer))
    def recv(self):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.RECV_CMD, 1)
        packer.pack(self.session)
        return self.pack(str(packer))
    def close(self):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.CLOSE_CMD, 1)
        packer.pack(self.session)
        return self.pack(str(packer))

class SockReqOperImpl:
    def __init__(self, operImpl = SockOperImpl()):
        pass
    def connect(self, remoteHost, remotePort):
    def send(self, content):
    def recv(self):
    def close(self):

class OperSessMgr:
    def __init__(self, sessOperClz):
        self.sessOperClz = sessOperClz
        self.curSessId = 0
        self.sessOperMap = {}
    def newSession(self):
        sessOper = self.sessOperClz(self.curSessId)
        self.sessOperMap[self.curSessId] = sessOper
        self.curSessId += 1
        return sessOper

class SockReqOperUnpacker:
    def __init__(self, operImplClz = SockReqOperImpl):
        self.operImplClz = operImplClz
    def unpack(self, packet):
        unpacker = Unpacker(StringStream(packet))
        packet = unpacker.unpack()
        unpacker = Unpacker(StringStream(packet))
        operCmd = unpacker.unpackNumber(1)
        unpacks = {
            CONNECT_CMD : self.unpackConnect,
            SEND_CMD : self.unpackSend,
            RECV_CMD : self.unpackRecv,
            CLOSE_CMD : self.unpackClose,
            }
        unpacks[operCmd](unpacker)
    def unpackConnect(self, unpacker):
        remoteHost = unpacker.unpack(1)
        remotePort = unpacker.unpackNumber(2)
        self.operImpl = operImplClz(self.session)
        self.operImpl.connect(remoteHost, remotePort)
    def unpackSend(self, unpacker):
        content = unpacker.unpack()
        self.operImpl.send(content)
    def unpackRecv(self, unpacker):
        self.operImpl.recv()
    def unpackClose(self, unpacker):
        self.operImpl.close()

class XorEncryptor:
    def __init__(self, key):
        self.key = key
    def __call__(self, content):
        result = ''
        for i in xrange(0, len(content)):
            result += chr(ord(content[i]) ^ ord(self.key[i % len(self.key)]))
        return result

XorDecryptor = XorEncryptor

class Socks5Operation:
    def __init__(self, operImpl = SocketOperation()):
        self.operImpl = operImpl
    def connect(self, remoteHost, remotePort):
        self.operImpl.connect(remoteHost, remotePort)
    def send(self, content):
        self.operImpl.send(content)
    def recv(self):
        return self.operImpl.recv()
    def close(self):
        self.operImpl.close()

class BufferedSocks5Operation:
    def __init__(self, maxSendCount = 10, maxRecvCount = 10, operImpl = Socks5Operation()):
        self.sendBufs = Queue.Queue(maxSendCount)
        self.recvBufs = Queue.Queue(maxRecvCount)
        self.operImpl = operImpl
    def connect(self, remoteHost, remotePort):
        self.operImpl.connect(remoteHost, remotePort)
        threading.Thread(target = self.sending).start()
        threading.Thread(target = self.recving).start()
    def send(self, content):
        self.sendBufs.put(content)
    def sending(self):
        try:
            while True:
                content = self.sendBufs.get()
                while not self.sendBufs.empty():
                    content += self.sendBufs.get()
                self.operImpl.send(content)
        finally:
            sendBufs = self.sendBufs
            self.sendBufs = None
            sendBufs.get_nowait()
    def recv(self):
        content = self.recvBufs.get()
        while not self.recvBufs.empty():
            content += self.recvBufs.get()
        return content
    def recving(self):
        try:
            while True:
                content = self.operImpl.recv()
                self.recvBufs.put(content)
        finally:
            recvBufs = self.recvBufs
            self.recvBufs = None
            recvBufs.put_nowait(None)
    def close(self):
        self.operImpl.close()
        sendBufs = self.sendBufs
        recvBufs = self.recvBufs
        self.sendBufs = None
        self.recvBufs = None
        try:
            if sendBufs != None:
                sendBufs.put_nowait(None)
        except Queue.Full:
            pass
        try:
            if sendBufs != None:
                sendBufs.get_nowait()
        except Queue.Empty:
            pass
        try:
            if recvBufs != None:
                recvBufs.put_nowait(None)
        except Queue.Full:
            pass
        try:
            if recvBufs != None:
                recvBufs.get_nowait()
        except Queue.Empty:
            pass
