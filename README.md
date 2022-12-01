## PLEXsim Viewer

### Usage


```python
from plexsimviewer import H5Viewer

fp = 'test.0.h5'

snap = H5Viewer(fp)
# file based의 경우 fp와 같은 디렉토리 내 iteration format이 같은 모든 파일 탐색
# group based의 경우 주어진 파일 내 cycle 탐색

snap
```

```python
snap = H5Viewer(fp, cycles=range(100, 200))  # list, range 등으로 cycles option 지정 가능
snap
```
```python
snap.stats
```
