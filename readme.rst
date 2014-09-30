=====
Intro
=====

`Shinpachi` is a cool little tool that can help you to debug network protocols
and APIs, especially HTTP and REST APIs.

In short, `Shinpachi` is basically a `Wireshark <https://www.wireshark.org/>`_
that can be plugged in between your client and server as an **HTTP proxy**. 

================
Basic Deployment
================

Start `redis` first::

    $ redis-server

And then, clone & run `Shinpachi`::

    $ git clone https://github.com/l04m33/shinpachi.git
    $ cd shinpachi
    $ pip install .
    $ shinpachi sample_config/test.ini

Now access http://localhost:8080 in your favorite browser. You shall see the
console running.

====
TODO
====

More docs.
