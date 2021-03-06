#!/usr/bin/env python3

#Copyright 2011-13 Newcastle University
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.


import datetime
import os
import io
import sys
import traceback
import shutil
from optparse import OptionParser
import examparser
from exam import Exam,ExamError
from xml2js import xml2js
from zipfile import ZipFile, ZipInfo
import xml.etree.ElementTree as etree
from itertools import count
import subprocess
import json


namespaces = {
    '': 'http://www.imsglobal.org/xsd/imscp_v1p1',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    'adlcp': 'http://www.adlnet.org/xsd/adlcp_v1p3',
    'adlseq': 'http://www.adlnet.org/xsd/adlseq_v1p3',
    'adlnav': 'http://www.adlnet.org/xsd/adlnav_v1p3',
    'imsss': 'http://www.imsglobal.org/xsd/imsss',
}

# because pre-py3.2 versions of etree always put a colon in front of tag names
# from http://stackoverflow.com/questions/8113296/supressing-namespace-prefixes-in-elementtree-1-2
if etree.VERSION[0:3] == '1.2':
    #in etree < 1.3, this is a workaround for supressing prefixes

    def fixtag(tag, namespaces):
        import string
        # given a decorated tag (of the form {uri}tag), return prefixed
        # tag and namespace declaration, if any
        if isinstance(tag, etree.QName):
            tag = tag.text
        namespace_uri, tag = tag[1:].split("}", 1)
        prefix = namespaces.get(namespace_uri)
        if namespace_uri not in namespaces:
            prefix = etree._namespace_map.get(namespace_uri)
            if namespace_uri not in etree._namespace_map:
                prefix = "ns%d" % len(namespaces)
            namespaces[namespace_uri] = prefix
            if prefix == "xml":
                xmlns = None
            else:
                if prefix is not None:
                    nsprefix = ':' + prefix
                else:
                    nsprefix = ''
                xmlns = ("xmlns%s" % nsprefix, namespace_uri)
        else:
            xmlns = None
        if prefix is not None:
            prefix += ":"
        else:
            prefix = ''

        return "%s%s" % (prefix, tag), xmlns

    etree.fixtag = fixtag
    for ns,url in namespaces.items():
        etree._namespace_map[url] = ns if len(ns) else None
else:
    #For etree > 1.3, use register_namespace function
    for ns,url in namespaces.items():
        try:
            etree.register_namespace(ns,url)        
        except AttributeError:
            etree._namespace_map[url]=ns


try:
    basestring
except NameError:
    basestring = str

def realFile(file):
    return not (file[-1]=='~' or file[-4:]=='.swp')

def collectFiles(options,dirs=[('runtime','.')]):

    resources=[x if isinstance(x,list) else [x,x] for x in options.resources]

    for name,path in resources:
        if os.path.isdir(path):
            dirs.append((os.path.join(os.getcwd(),path),os.path.join('resources',name)))


    extensions = [os.path.join(options.path,'extensions',x) for x in options.extensions]
    extfiles = [
            (os.path.join(os.getcwd(),x),os.path.join('extensions',os.path.split(x)[1]))
                for x in extensions if os.path.isdir(x)
            ]
    dirs += extfiles

    for themepath in options.themepaths:
        dirs.append((os.path.join(themepath,'files'),'.'))

    files = {}
    for (src,dst) in dirs:
        src = os.path.join(options.path,src)
        for x in os.walk(src, followlinks=options.followlinks):
            xsrc = x[0]
            xdst = x[0].replace(src,dst,1)
            for y in filter(realFile,x[2]):
                files[os.path.join(xdst,y)] = os.path.join(xsrc,y) 

    for name,path in resources:
        if not os.path.isdir(path):
            files[os.path.join('resources',name)] = os.path.join(options.path,path)
    
    return files

def compileToDir(exam,files,options):
    if options.action == 'clean':
        try:
            shutil.rmtree(options.output)
        except OSError:
            pass
    try:
        os.mkdir(options.output)
    except OSError:
        pass
    
    def makepath(path):    #make sure directory hierarchy of path exists by recursively creating directories
        dir = os.path.dirname(path)
        if not os.path.exists(dir):
            makepath(dir)
            try:
                os.mkdir(dir)
            except OSError:
                pass

    for (dst,src) in files.items():
        dst = os.path.join(options.output,dst)
        makepath(dst)
        if isinstance(src,basestring):
            if options.action=='clean' or not os.path.exists(dst) or os.path.getmtime(src)>os.path.getmtime(dst):
                shutil.copyfile(src,dst)
        else:
            shutil.copyfileobj(src,open(dst,'w',encoding='utf-8'))
    
    print("Exam created in %s" % os.path.relpath(options.output))

def compileToZip(exam,files,options):
    
    def cleanpath(path):
        if path=='': 
            return ''
        dirname, basename = os.path.split(path)
        dirname=cleanpath(dirname)
        if basename!='.':
            dirname = os.path.join(dirname,basename)
        return dirname

    f = ZipFile(options.output,'w')

    for (dst,src) in files.items():
        dst = ZipInfo(cleanpath(dst))
        dst.external_attr = 0o644<<16
        dst.date_time = datetime.datetime.today().timetuple()
        if isinstance(src,basestring):
            f.writestr(dst,open(src,'rb').read())
        else:
            f.writestr(dst,src.read())



    print("Exam created in %s" % os.path.relpath(options.output))

    f.close()

def makeExam(options):
    try:
        exam = Exam.fromstring(options.source)
        examXML = exam.tostring()
        options.resources = exam.resources
        options.extensions = exam.extensions
    except ExamError as err:
        raise Exception('Error constructing exam:\n%s' % err)
    except examparser.ParseError as err:
        raise Exception("Failed to compile exam due to parsing error.\n%s" % err)
    except:
        raise Exception('Failed to compile exam.')

    options.examXML = examXML
    options.xmls = xml2js(options)

    files = collectFiles(options)
    files[os.path.join('.','settings.js')] = io.StringIO(options.xmls)

    localePath = os.path.join(options.path,'locales')
    locales = {}
    for fname in os.listdir(localePath):
        name,ext = os.path.splitext(fname)
        if ext.lower()=='.json':
            with open(os.path.join(localePath,fname),encoding='utf-8') as f:
                locales[name] = {'translation': json.loads(f.read())}

    locale_js = """
    Numbas.queueScript('localisation-resources',['i18next'],function() {{
    Numbas.locale = {{
        preferred_locale: {},
        resources: {}
    }}
    }});
    """.format(json.dumps(options.locale),json.dumps(locales))
    files[os.path.join('.','locale.js')] = io.StringIO(locale_js)

    if options.scorm:
        IMSprefix = '{http://www.imsglobal.org/xsd/imscp_v1p1}'
        manifest = etree.fromstring(open(os.path.join(options.path,'scormfiles','imsmanifest.xml')).read())
        manifest.attrib['identifier'] = 'Numbas: %s' % exam.name
        manifest.find('%sorganizations/%sorganization/%stitle' % (IMSprefix,IMSprefix,IMSprefix)).text = exam.name
        def to_relative_url(path):
            path = os.path.normpath(path)
            bits = []
            head,tail=os.path.split(path)
            while head!='':
                bits.insert(0,tail)
                head,tail=os.path.split(head)
            bits.insert(0,tail)
            return '/'.join(bits)

        resource_files = [to_relative_url(x) for x in files.keys()]

        resource_element = manifest.find('%sresources/%sresource' % (IMSprefix,IMSprefix))
        for filename in resource_files:
            file_element = etree.Element('file')
            file_element.attrib = {'href': filename}
            resource_element.append(file_element)

        files.update(collectFiles(options,[('scormfiles','.')]))

        manifest_string = etree.tostring(manifest)
        try:
            manifest_string = manifest_string.decode('utf-8')
        except AttributeError:
            pass

        files[os.path.join('.','imsmanifest.xml')] = io.StringIO(manifest_string)

    stylesheets = [(dst,src) for dst,src in files.items() if os.path.splitext(dst)[1]=='.css']
    for dst,src in stylesheets:
        del files[dst]
    stylesheets = [src for dst,src in stylesheets]
    stylesheets = '\n'.join(open(src,encoding='utf-8').read() if isinstance(src,basestring) else src.read() for src in stylesheets)
    files[os.path.join('.','styles.css')] = io.StringIO(stylesheets)
    

    javascripts = [(dst,src) for dst,src in files.items() if os.path.splitext(dst)[1]=='.js']
    for dst,src in javascripts:
        del files[dst]

    javascripts = [src for dst,src in javascripts]
    numbas_loader_path = os.path.join(options.path,'runtime','scripts','numbas.js')
    javascripts.remove(numbas_loader_path)
    javascripts.insert(0,numbas_loader_path)
    javascripts = '\n'.join(open(src,encoding='utf-8').read() if isinstance(src,basestring) else src.read() for src in javascripts)
    files[os.path.join('.','scripts.js')] = io.StringIO(javascripts)

    if options.minify:
        for dst,src in files.items():
            if isinstance(src,basestring) and os.path.splitext(dst)[1] == '.js':
                p = subprocess.Popen([options.minify,src],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                out,err = p.communicate()
                code = p.poll()
                if code != 0:
                    raise Exception('Failed to minify %s with minifier %s' % (src,options.minify))
                else:
                    files[dst] = io.StringIO(out.decode('utf-8'))
        
    if options.zip:
        compileToZip(exam,files,options)
    else:
        compileToDir(exam,files,options)

def get_theme_path(theme,options):
    if os.path.exists(theme):
        return theme
    else:
        ntheme = os.path.join(options.path,'themes',theme)
        if os.path.exists(ntheme):
            return ntheme
        else:
            raise Exception("Couldn't find theme %s" % theme)

def run():
    if 'assesspath' in os.environ:
        path = os.environ['assesspath']
    else:
        path = os.getcwd()

    parser = OptionParser(usage="usage: %prog [options] source")
    parser.add_option('-t','--theme',
                        dest='theme',
                        action='store',
                        type='string',
                        default='default',
                        help='Path to the theme to use'
        )
    parser.add_option('-f','--followlinks',
                        dest='followlinks',
                        action='store_true',
                        default=False,
                        help='Whether to follow symbolic links in the theme directories'
        )
    parser.add_option('-u','--update',
                        dest='action',
                        action='store_const',
                        const='update',
                        default='update',
                        help='Update an existing exam.'
        )
    parser.add_option('-c','--clean',
                        dest='action',
                        action='store_const',
                        const='clean',
                        help='Start afresh, deleting any existing exam in the target path'
        )
    parser.add_option('-z','--zip',
                        dest = 'zip',
                        action='store_true',
                        default=False,
                        help='Create a zip file instead of a directory'
        )
    parser.add_option('-s','--scorm',
                        dest='scorm',
                        action='store_true',
                        default=False,
                        help='Include the files necessary to make a SCORM package'
        )
    parser.add_option('-p','--path',
                        dest='path',
                        default=path,
                        help='The path to the Numbas files (or you can set the ASSESSPATH environment variable)'
        )
    parser.add_option('-o','--output',
                        dest='output',
                        help='The target path'
        )
    parser.add_option('--pipein',
                        dest='pipein',
                        action='store_true',
                        default=False,
                        help="Read .exam from stdin")
    parser.add_option('-l','--language',
                        dest='locale',
                        default='en-GB',
                        help='Language (ISO language code) to use when displaying text')
    parser.add_option('--minify',
                        dest='minify',
                        default='',
                        help='Path to Javascript minifier. If not given, no minification is performed.')

    (options,args) = parser.parse_args()

    if options.pipein:
        options.source = sys.stdin.detach().read().decode('utf-8')
        options.sourcedir = os.getcwd()
        if not options.output:
            options.output = os.path.join(path,'output','exam')
    else:
        try:
            source_path = args[0]
        except IndexError:
            parser.print_help()
            return

        if not os.path.exists(source_path):
            osource = source_path
            source_path = os.path.join(path,source_path)
            if not os.path.exists(source_path):
                print("Couldn't find source file %s" % osource)
                exit(1)
        options.source=open(source_path,encoding='utf-8').read()
        options.sourcedir = os.path.dirname(source_path)

        if not options.output:
            output = os.path.basename(os.path.splitext(source_path)[0])
            if options.zip:
                output += '.zip'
            options.output=os.path.join(path,'output',output)
    

    options.themepaths = [options.theme]
    for theme,i in zip(options.themepaths,count()):
        theme = options.themepaths[i] = get_theme_path(theme,options)
        inherit_file = os.path.join(theme,'inherit.txt')
        if os.path.exists(inherit_file):
            options.themepaths += open(inherit_file).read().splitlines()

    options.themepaths.reverse()

    try:
        makeExam(options)
    except Exception as err:
        sys.stderr.write(str(err)+'\n')
        _,_,exc_traceback = sys.exc_info()
        traceback.print_exc()
        exit(1)

if __name__ == '__main__':
    run()

