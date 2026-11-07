'use strict';
// Generate disposable identities. This file never reads a live server's data.
const fs = require('node:fs');
const { Store } = require('../../../zmala_server/store');
const { profile, random } = require('../../../zmala_server/defaults');
if (fs.existsSync('/lab/seeded')) process.exit(0);
const store = new Store('/lab/server');
store.value.host = '10.231.100.13';
store.value.users = {};
store.value.profiles = {};
store.value.groups = {
  lab: { name: 'Lab', description: 'Disposable NAT test', members: ['a', 'b'] },
};
store.value.local_terminal_id = 'a';
for (const id of ['a', 'b']) {
  const token = random();
  store.value.users[id] = {
    name: id,
    type: 'terminal',
    emails: [],
    password: random(),
    device_id: id,
    device_token: token,
    auto_answer: false,
    auto_answer_seconds: 10,
  };
  store.value.profiles[id] = { ...profile(id), video_resolution: '480p', video_fps: 15 };
  fs.writeFileSync(`/lab/${id}.json`, JSON.stringify({ token }), { mode: 0o600 });
}
store.save();
fs.writeFileSync('/lab/seeded', '1');
console.log('Created two disposable terminal identities.');
