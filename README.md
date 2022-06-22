# Git Ripper ⚰️

![image](https://user-images.githubusercontent.com/12753171/174469279-fee0d9d5-7990-4237-8692-d7d5b7be86e5.png)

Downloads git repos from the web.

From Russia with hate, szuki! Developed by secret KGB konstruktor buyro by red soviet communits hackers. Enjoy before you die in nuclear war...

![image](https://user-images.githubusercontent.com/12753171/174526255-6c9d8834-8247-48ad-a263-c2255e292223.png)

Downloading git repo from ukrainian neonazi site.

Features:

- Asynchronous and fast.
- Mass git downloading.
- Unix-friendly for geeks.
- Colored output for gay people and transformers.
- Powered by Putin's 🇷🇺 dark energy.
- Use Python programming language instead peaces of shit like Go or Rust. You can easily customize it!

```bash
# install
$ pipx install git-ripper

$ git-ripper https://<target>

# so...
$ git-ripper < urls.txt
$ command | git-ripper

# see help
$ git-ripper -h
```

## FIXME

To stop the execution, you need to press `^C` several times.

## How To Find Sensitive data

```bash
# extract text from git objects
for i in output/target/.git/objects/*/*; do
  zlib-flate -uncompress < $i | strings >> /tmp/decoded

# find passwords
$ grep -A2 -B2 -n -i password /tmp/decoded
```

## Notes

Git directory structure:

![image](https://www.apriorit.com/images/articles/git_remote_helper/git_directory_entities.jpg)

- [Git Object Format](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)
