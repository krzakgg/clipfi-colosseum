-- KEYS: rate limit, dedup, minute bucket, bucket index, event stream, ip uniques
-- ARGV: rate limit, ttl to midnight, link id, epoch minute, bucket ttl,
--       stream maxlen, time ms, visitor hash, referer host, max uniques per ip

local hits = redis.call('INCR', KEYS[1])
if hits == 1 then
    redis.call('EXPIRE', KEYS[1], 60)
end
if hits > tonumber(ARGV[1]) then
    return 'ratelimited'
end

local first_today = redis.call('SET', KEYS[2], '1', 'NX', 'EX', ARGV[2])
local unique = first_today and 1 or 0

-- cap uniques per address, otherwise rotating the User-Agent mints new ones
if unique == 1 then
    local ip_uniques = redis.call('INCR', KEYS[6])
    if ip_uniques == 1 then
        redis.call('EXPIRE', KEYS[6], ARGV[2])
    end
    if ip_uniques > tonumber(ARGV[10]) then
        unique = 0
    end
end

if redis.call('HINCRBY', KEYS[3], ARGV[3] .. ':r', 1) == 1 then
    redis.call('EXPIRE', KEYS[3], ARGV[5])
end
if unique == 1 then
    redis.call('HINCRBY', KEYS[3], ARGV[3] .. ':u', 1)
end
redis.call('ZADD', KEYS[4], ARGV[4], ARGV[4])
redis.call('XADD', KEYS[5], 'MAXLEN', '~', ARGV[6], '*',
    'l', ARGV[3], 't', ARGV[7], 'u', unique, 'v', ARGV[8], 'r', ARGV[9])

if unique == 1 then
    return 'unique'
end
return 'repeat'
