const express = require('express');
const bodyParser = require('body-parser');
const { validateToken } = require('./auth');
const { getUser } = require('./users');

const app = express();
const router = express.Router();

app.use(bodyParser);
app.use('/api', router);

function healthz(req, res) { res.json({ ok: true }); }
function createUser(req, res) { res.json(getUser(1)); }
function readUser(req, res) { res.json(getUser(req.params.id)); }

app.get('/healthz', healthz);
router.post('/users', createUser);
router.get('/users/:id', readUser);

app.listen(3000);
