"""In-memory Redis fallback for development only."""
import time

class MockRedis:
    """Mock Redis for development without Redis server"""
    
    def __init__(self):
        self.data = {}
        self.sets = {}
        self.lists = {}
        self.expiry = {}

    async def ping(self):
        return True

    async def hset(self, name, key=None, value=None, mapping=None):
        if name not in self.data:
            self.data[name] = {}
        if mapping:
            self.data[name].update(mapping)
        elif key:
            self.data[name][key] = value

    async def hgetall(self, name):
        return self.data.get(name, {})

    async def hget(self, name, key):
        return self.data.get(name, {}).get(key)
    async def hdel(self, name, *keys):
        """Delete hash fields"""
        if name in self.data:
            for key in keys:
                self.data[name].pop(key, None)
            # Remove hash if empty
            if not self.data[name]:
                del self.data[name]
        return len(keys)
    
    async def hkeys(self, name):
        """Get all keys in a hash"""
        return list(self.data.get(name, {}).keys())
    
    async def sadd(self, name, *values):
        if name not in self.sets:
            self.sets[name] = set()
        self.sets[name].update(values)

    async def smembers(self, name):
        return self.sets.get(name, set())

    async def sismember(self, name, value):
        return value in self.sets.get(name, set())

    async def srem(self, name, *values):
        if name in self.sets:
            self.sets[name].difference_update(values)

    async def lpush(self, name, *values):
        if name not in self.lists:
            self.lists[name] = []
        self.lists[name] = list(values) + self.lists[name]

    async def lrange(self, name, start, end):
        if name not in self.lists:
            return []
        return self.lists[name][start:end+1] if end >= 0 else self.lists[name][start:]

    async def ltrim(self, name, start, end):
        if name in self.lists:
            self.lists[name] = self.lists[name][start:end+1]

    async def delete(self, *names):
        for name in names:
            self.data.pop(name, None)
            self.sets.pop(name, None)
            self.lists.pop(name, None)
            self.expiry.pop(name, None)

    async def get(self, name):
        """Get a single value"""
        return self.data.get(name)

    async def set(self, name, value, ex=None):
        """Set a value with optional expiry"""
        self.data[name] = value
        if ex:
            self.expiry[name] = ex
        return True

    async def setex(self, name, time, value):
        """Set value with expiration"""
        self.data[name] = value
        self.expiry[name] = time
        return True

    async def expire(self, name, time):
        """Set expiration time for a key"""
        self.expiry[name] = time
        return True
    
    async def ttl(self, name):
        """Get time to live for a key"""
        return self.expiry.get(name, -1)

    async def keys(self, pattern):
        """Get keys matching pattern"""
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            # Combine all dictionaries
            all_keys = list(self.data.keys()) + list(self.sets.keys()) + list(self.lists.keys())
            return [k for k in all_keys if k.startswith(prefix)]
        return []

    def pipeline(self):
        """Mock pipeline for batch operations"""
        return MockPipeline(self)

    async def execute(self):
        """Execute pipeline"""
        results = []
        for cmd in self.commands:
            if cmd[0] == 'set' or cmd[0] == 'delete' or cmd[0] == 'expire':
                await getattr(self.redis, cmd[0])(*cmd[1:])
                results.append(True)
            elif cmd[0] == 'get':
                results.append(await self.redis.get(cmd[1]))
            elif cmd[0] == 'hget':
                results.append(await self.redis.hget(cmd[1], cmd[2]))
            elif cmd[0] == 'hkeys':
                results.append(await self.redis.hkeys(cmd[1]))
            else:
                results.append(None)
        return results 
        
class MockPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []
    
    def set(self, key, value, ex=None):
        self.commands.append(('set', key, value, ex))
        return self
    
    def get(self, key):
        self.commands.append(('get', key))
        return self
    
    async def execute(self):
        results = []
        for cmd in self.commands:
            if cmd[0] == 'set':
                await self.redis.set(cmd[1], cmd[2], ex=cmd[3])
                results.append(True)
            elif cmd[0] == 'get':
                results.append(await self.redis.get(cmd[1]))
        return results

