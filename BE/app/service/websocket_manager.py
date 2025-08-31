import json
import uuid
import asyncio
import weakref
from fastapi import WebSocket
from typing import Set, Dict, List, Optional
from app.util.database.redis import RedisManager


class ConnectionManager:
    def __init__(self):
        self.activate_connections: Dict[int, Dict[int, List[WebSocket]]] = {}
        self.connection_metadata: Dict[WebSocket, Dict] = weakref.WeakKeyDictionary()
        self._lock = asyncio.Lock() # 동시성 제어를 위한 락
        self.server_id = uuid.uuid4().hex[:8]  # 서버 고유 ID
        self.socket_type: str = None
        self._redis_client: Optional[str] = None
        self._pubsub_client: Optional[str] = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._is_listening = False
        self._pending_broadcasts = {}  # 브로드캐스트 배치 처리용
        self._batch_task: Optional[asyncio.Task] = None
    
    async def _get_redis_client(self):
        """Redis 클라이언트 lazy 초기화"""
        if self._redis_client is None:
            self._redis_client = await RedisManager.get_redis()
        return self._redis_client
    
    async def _get_pubsub_client(self):
        """Pub/Sub 클라이언트 lazy 초기화"""
        if self._pubsub_client is None:
            self._pubsub_client = await RedisManager.get_pubsub_redis()
        return self._pubsub_client
    
    async def connect(self, socket_type: str, workspace_id: int, tab_id: int, websocket: WebSocket):
        await websocket.accept()
        
        self.socket_type = socket_type
        
        needs_init = False
        if (socket_type not in self.activate_connections or 
            workspace_id not in self.activate_connections.get(socket_type, {}) or 
            tab_id not in self.activate_connections.get(socket_type, {}).get(workspace_id, {})):
            needs_init = True

        if needs_init:
            async with self._lock:
                # 더블 체킹으로 다른 스레드가 이미 초기화했는지 확인
                if socket_type not in self.activate_connections:
                    self.activate_connections[socket_type] = {}
                if workspace_id not in self.activate_connections[socket_type]:
                    self.activate_connections[socket_type][workspace_id] = {}
                if tab_id not in self.activate_connections[socket_type][workspace_id]:
                    self.activate_connections[socket_type][workspace_id][tab_id] = set()
        
        # 웹소켓 추가만 락으로 보호 (최소한의 임계 영역)
        async with self._lock:
            self.activate_connections[socket_type][workspace_id][tab_id].add(websocket)

        # Redis 초기화와 방 등록을 백그라운드에서 처리 (연결 속도 향상)
        asyncio.create_task(self._initialize_and_register_room(socket_type, workspace_id, tab_id))

        # 메타데이터 저장
        self.connection_metadata[websocket] = {
            "socket_type": socket_type,
            "workspace_id": workspace_id,
            "tab_id": tab_id,
            "connected_at": asyncio.get_event_loop().time()
        }
    
    async def disconnect(self, workspace_id: int, tab_id: int, websocket: WebSocket):
        async with self._lock: 
            try:
                metadata = self.connection_metadata.get(websocket) 
                if not metadata:
                    return

                socket_type = metadata["socket_type"]
                metadata["is_active"] = False
                
                # 안전한 연결 제거
                removed = await self._safe_remove_connection(socket_type, workspace_id, tab_id, websocket)
                if not removed:
                    await self._close_websocket_safely(websocket)
            
            except Exception as e:
                await self._force_cleanup_websocket(websocket)
    
    async def _safe_remove_connection(self, socket_type: str, workspace_id: int, tab_id: int, websocket: WebSocket) -> bool:
        """안전한 연결 제거 (KeyError 방지)"""
        try:
            # 단계별 존재 확인
            if socket_type not in self.activate_connections:
                return False
            if workspace_id not in self.activate_connections[socket_type]:
                return False
            if tab_id not in self.activate_connections[socket_type][workspace_id]:
                return False
            tab_connections = self.activate_connections[socket_type][workspace_id][tab_id]
            
            if websocket in tab_connections:
                tab_connections.remove(websocket)
                await self._cleanup_empty_containers(socket_type, workspace_id, tab_id)
                return True
            return False

        except Exception as e:
            return False
        
    async def _cleanup_empty_containers(self, socket_type: str, workspace_id: int, tab_id: int):
        """빈 컨테이너 정리"""
        try: 
            # 탭 레벨 정리
            if not self.activate_connections[socket_type][workspace_id][tab_id]: 
                del self.activate_connections[socket_type][workspace_id][tab_id]
            if not self.activate_connections[socket_type][workspace_id]:
                del self.activate_connections[socket_type][workspace_id]
            
            # 빈 탭이면 Redis에서도 방 제거 (백그라운드 처리)  
            if not self.activate_connections[socket_type][workspace_id].get(tab_id):
                asyncio.create_task(self._unregister_room_from_redis(socket_type, workspace_id, tab_id))
        
        except KeyError:
            pass # 이미 다른 서버에서 정리함
    
    async def _close_websocket_safely(self, websocket: WebSocket):
        """웹소켓 안전한 종료"""
        if websocket.client_state.value in [1, 2]:
            await websocket.close()
    
    async def _force_cleanup_websocket(self, websocket: WebSocket):
        """강제 웹소켓 정리 (에러 발생 시 최후 수단)"""
        try:
            # 모든 연결에서 해당 Websocket 제거
            for socket_type in list(self.activate_connections.keys()):
                for workspace_id in list(self.activate_connections[socket_type].keys()):
                    for tab_id in list(self.activate_connections[socket_type][workspace_id].keys()):
                        connections = self.activate_connections[socket_type][workspace_id][tab_id]
                        if websocket in connections:
                            connections.discard(websocket)
                            await self._cleanup_empty_containers(socket_type, workspace_id, tab_id)
                            # 방에 연결이 없으면 Redis에서도 제거 (백그라운드 처리)
                            asyncio.create_task(self._unregister_room_from_redis(socket_type, workspace_id, tab_id))
        except Exception as e:
            print(f"웹소켓 제거 중 에러 발생: {e}")
    
    async def broadcast_local(self, workspace_id: int, tab_id: int, message: str):
        """로컬 서버의 연결된 클라이언트들에게만 브로드캐스트"""
        connections = self.activate_connections.get(self.socket_type, {}).get(workspace_id, {}).get(tab_id, set())
        for connection in list(connections):
            try:
                await connection.send_text(message)
            except Exception:
                connections.discard(connection)
    
    async def broadcast(self, workspace_id: int, tab_id: int, message: str):
        """최적화된 브로드캐스트: 로컬 즉시 전송 + Redis 배치 처리"""
        # 로컬 연결된 클라이언트들에게 즉시 전송
        await self.broadcast_local(workspace_id, tab_id, message)
        
        # Redis 브로드캐스트를 배치로 처리
        await self._queue_redis_broadcast(workspace_id, tab_id, message)
    
    async def _ensure_redis_initialized(self):
        """Redis 클라이언트 미리 초기화"""
        if self._redis_client is None:
            self._redis_client = await RedisManager.get_redis()
        if self._pubsub_client is None:
            self._pubsub_client = await RedisManager.get_pubsub_redis()
    
    async def _queue_redis_broadcast(self, workspace_id: int, tab_id: int, message: str):
        """Redis 브로드캐스트를 큐에 추가하고 배치 처리"""
        channel = f"type:{self.socket_type}:workspace:{workspace_id}:tab:{tab_id}"
        
        if channel not in self._pending_broadcasts:
            self._pending_broadcasts[channel] = []
        
        self._pending_broadcasts[channel].append({
            "message": message,
            "sender_server": self.server_id,
            "timestamp": asyncio.get_event_loop().time()
        })
        
        # 배치 처리 태스크가 없으면 시작
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._process_batch_broadcasts())
    
    async def _process_batch_broadcasts(self):
        """배치로 모인 브로드캐스트들을 처리"""
        await asyncio.sleep(0.001)  # 1ms 대기로 배치 수집
        
        if not self._pending_broadcasts:
            return
            
        try:
            redis_client = await self._get_redis_client()
            pipe = redis_client.pipeline()
            
            # 배치로 모든 메시지 publish
            for channel, messages in self._pending_broadcasts.items():
                for msg_data in messages:
                    pipe.publish(channel, json.dumps(msg_data))
            
            await pipe.execute()
            self._pending_broadcasts.clear()
            
        except Exception as e:
            print(f"배치 Redis publish 에러: {e}")
            self._pending_broadcasts.clear()
    
    async def _start_redis_listener(self):
        """Redis Pub/Sub 리스너 시작 (타입별 구독으로 최적화)"""
        if self._is_listening:
            return
            
        try:
            self._is_listening = True
            self._pubsub_task = asyncio.create_task(self._redis_listener())
        except Exception as e:
            print(f"Redis 리스너 시작 에러: {e}")
            self._is_listening = False
    
    async def _redis_listener(self):
        """Redis 메시지 수신 및 처리 (타입별 구독)"""
        try:
            pubsub_client = await self._get_pubsub_client()
            pubsub = pubsub_client.pubsub()

            # 해당 타입의 채널만 구독 (더 효율적)
            pattern = f"type:{self.socket_type}:workspace:*:tab:*"
            await pubsub.psubscribe(pattern)

            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    await self._handle_redis_message(message)

        except Exception as e:
            print(f"Redis 리스너 에러: {e}")
        finally:
            self._is_listening = False
    
    async def _handle_redis_message(self, redis_message):
        """Redis에서 받은 메시지 처리"""
        try:
            channel = redis_message["channel"]
            data = json.loads(redis_message["data"])
            # print(data)
            
            # 자신이 보낸 메시지는 무시
            if data.get("sender_server") == self.server_id:
                return
            
            # 채널에서 workspace_id, tab_id 추출
            parts = channel.split(":")
            if len(parts) >= 6:
                workspace_id = int(parts[3])
                tab_id = int(parts[5])
                message = data.get("message", "")
                # 로컬 연결된 클라이언트들에게 브로드캐스트
                await self.broadcast_local(workspace_id, tab_id, message)
                
        except Exception as e:
            print(f"Redis 메시지 처리 에러: {e}")
    
    async def cleanup(self):
        """리소스 정리"""
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
        
        await RedisManager.close_connections()
    
    async def _register_room_in_redis(self, socket_type: str, workspace_id: int, tab_id: int):
        """Redis에 방 정보 등록 (Pipeline으로 최적화)"""
        try:
            redis_client = await self._get_redis_client()
            room_key = f"room:{socket_type}:workspace:{workspace_id}:tab:{tab_id}"
            server_key = f"server:{self.server_id}"
            
            # Pipeline으로 모든 명령어를 한 번에 실행
            pipe = redis_client.pipeline()
            pipe.setex(room_key, 3600, f"active_on_{self.server_id}")
            pipe.sadd(server_key, room_key)
            pipe.expire(server_key, 3600)
            pipe.sadd("active_rooms", room_key)
            await pipe.execute()
            
        except Exception as e:
            print(f"Redis 방 등록 에러: {e}")
    
    async def _unregister_room_from_redis(self, socket_type: str, workspace_id: int, tab_id: int):
        """Redis에서 방 정보 제거 (연결이 없을 때)"""
        try:
            # 로컬에 연결이 남아있는지 확인
            connections = self.activate_connections.get(socket_type, {}).get(workspace_id, {}).get(tab_id, set())
            if connections:
                return  # 아직 연결이 있으면 제거하지 않음
                
            redis_client = await self._get_redis_client()
            room_key = f"room:{socket_type}:workspace:{workspace_id}:tab:{tab_id}"
            server_key = f"server:{self.server_id}"
            
            # 방 정보 제거
            await redis_client.delete(room_key)
            
            # 서버별 방 목록에서 제거
            await redis_client.srem(server_key, room_key)
            
            # 전체 활성 방 목록에서 제거
            await redis_client.srem("active_rooms", room_key)
            
        except Exception as e:
            print(f"Redis 방 제거 에러: {e}")
    
    async def _initialize_and_register_room(self, socket_type: str, workspace_id: int, tab_id: int):
        """Redis 초기화와 방 등록을 한 번에 처리"""
        try:
            # Redis 초기화
            await self._ensure_redis_initialized()
            
            # 리스너 시작 (한 번만)
            if not self._is_listening:
                await self._start_redis_listener()
            
            # 방 등록
            await self._register_room_in_redis(socket_type, workspace_id, tab_id)
        except Exception as e:
            print(f"Redis 초기화 및 방 등록 에러: {e}")
