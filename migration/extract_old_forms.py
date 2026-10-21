import struct,json,sys,re
d=open(r'E:\humancapital\HumanCapitalXE4.exe','rb').read()
class P:
    def __init__(s,b,i):s.b=b;s.i=i
    def u8(s):v=s.b[s.i];s.i+=1;return v
    def rd(s,f):
        n=struct.calcsize(f);v=struct.unpack_from(f,s.b,s.i)[0];s.i+=n;return v
    def sstr(s):
        n=s.u8();v=s.b[s.i:s.i+n].decode('cp1251',errors='replace');s.i+=n;return v
    def value(s):
        t=s.u8()
        if t==0:return None
        if t==1:
            l=[]
            while s.b[s.i]!=0:l.append(s.value())
            s.i+=1;return l
        if t==2:return s.rd('<b')
        if t==3:return s.rd('<h')
        if t==4:return s.rd('<i')
        if t==5:s.i+=10;return 'ext'
        if t in(6,7):return s.sstr() if t==6 else ('@'+s.sstr())
        if t==8:return False
        if t==9:return True
        if t==10:
            n=s.rd('<I');s.i+=n;return '<bin>'
        if t==11:
            l=[]
            while s.b[s.i]!=0:l.append(s.sstr())
            s.i+=1;return {'set':l}
        if t==12:
            n=s.rd('<I');v=s.b[s.i:s.i+n].decode('cp1251',errors='replace');s.i+=n;return v
        if t==13:return None
        if t==14:
            l=[]
            while s.b[s.i]!=0:
                if s.b[s.i]==1:s.i+=1
                elif s.b[s.i] in(2,3,4):
                    s.value()
                item={}
                while s.b[s.i]!=0:
                    k=s.sstr();item[k]=s.value()
                s.i+=1;l.append(item)
            s.i+=1;return l
        if t==15:s.i+=4;return 'single'
        if t==16:s.i+=8;return 'cur'
        if t==17:s.i+=8;return 'date'
        if t==18:
            n=s.rd('<I');v=s.b[s.i:s.i+2*n].decode('utf-16le',errors='replace');s.i+=2*n;return v
        if t==19:return s.rd('<q')
        if t==20:
            n=s.rd('<I');v=s.b[s.i:s.i+n].decode('utf-8',errors='replace');s.i+=n;return v
        if t==21:s.i+=8;return 'dbl'
        raise ValueError('type %d at %d'%(t,s.i))
    def obj(s):
        if s.b[s.i]>=0xF0:
            f=s.u8()
            if f&2:  # position
                s.value()
        cls=s.sstr();name=s.sstr()
        o={'class':cls,'name':name,'props':{},'kids':[]}
        while s.b[s.i]!=0:
            k=s.sstr();o['props'][k]=s.value()
        s.i+=1
        while s.b[s.i]!=0:o['kids'].append(s.obj())
        s.i+=1
        return o
forms=[];fail=0;pos=0
while True:
    i=d.find(b'TPF0',pos)
    if i<0:break
    pos=i+4
    try:
        p=P(d,i+4);o=p.obj();forms.append(o)
        pos=p.i
    except Exception as e:
        fail+=1
json.dump(forms,open('forms.json','w',encoding='utf-8'))
print(len(forms),'forms parsed;',fail,'failed')
