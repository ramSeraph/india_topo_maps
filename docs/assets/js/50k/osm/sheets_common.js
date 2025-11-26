function fileSize(size) {
    var i = Math.floor(Math.log(size) / Math.log(1024));
    return (size / Math.pow(1024, i)).toFixed(2) + ' ' + ['B', 'kB', 'MB', 'GB', 'TB'][i];
}

parseListing = (listingText) => {
    var entryTexts = listingText.trim().split('\n');
    var data = {};
    // skip header
    for (var i = 1; i < entryTexts.length; i++) {
        var entryText = entryTexts[i].trim();
        if (entryText === '') {
            continue;
        }
        var pieces = entryText.split(',');
        if (pieces.length < 3) continue;
        var name = pieces[0];
        var size = pieces[1];
        var url = pieces[2];
        data[name] = { size: size, url: url };
    }
    return data;
}

function fetchSheetList(listFilename, callback) {
    var url = `../${listFilename}`
    var httpRequest = new XMLHttpRequest()
    
    alertContents = () => {
        if (httpRequest.readyState === XMLHttpRequest.DONE) {
            if (httpRequest.status === 200) {
                var data = parseListing(httpRequest.responseText)
                callback(null, data)
            } else {
                callback('Remote Request failed', null)
                console.log(`Remote Request failed with ${httpRequest.status} and text: ${httpRequest.responseText}`)
            }
        }
    }
     
    if (!httpRequest) {
        callback('Internal Error', null)
        console.log('Giving up :( Cannot create an XMLHTTP instance')
        return
    }
    httpRequest.onreadystatechange = alertContents
    httpRequest.open('GET', url)
    httpRequest.send()
    console.log('call sent')
}

function getStatusData(cb) {
    var gtiffSizeData = null
    var pdfSizeData = null
    var jpgSizeData = null
    var err = null

    collate = () => {
        if (gtiffSizeData === null || pdfSizeData === null || jpgSizeData === null) {
            return
        }
        if (err !== null) {
            cb(err, null)
            return
        }
        var statusInfo = {}
        
        // Helper function to get sheet numbers from a display name
        const getSheetNumbers = (sheetNoDisp) => {
            // Check if it's a joint sheet like "66E/1-66E/2"
            if (sheetNoDisp.includes('-')) {
                const parts = sheetNoDisp.split('-');
                return parts;
            }
            return [sheetNoDisp];
        }
        
        for (const name in pdfSizeData) {
            const pdfInfo = pdfSizeData[name];
            const sheetNoDisp = name.replace(/_/g, '/').replace('.pdf', '');
            const fsize = fileSize(pdfInfo.size);
            const sheetNumbers = getSheetNumbers(sheetNoDisp);
            
            for (const sheetNo of sheetNumbers) {
                if (!(sheetNo in statusInfo)) {
                    statusInfo[sheetNo] = {};
                }
                statusInfo[sheetNo]['status'] = 'found';
                statusInfo[sheetNo]['pdfUrl'] = pdfInfo.url;
                statusInfo[sheetNo]['pdfFilesize'] = fsize;
            }
        }


        for (const name in gtiffSizeData) {
            const gtiffInfo = gtiffSizeData[name];
            const sheetNoDisp = name.replace(/_/g, '/').replace('.tif', '');
            const fsize = fileSize(gtiffInfo.size);
            const sheetNumbers = getSheetNumbers(sheetNoDisp);
            
            for (const sheetNo of sheetNumbers) {
                if (!(sheetNo in statusInfo)) {
                    statusInfo[sheetNo] = {};
                }
                statusInfo[sheetNo]['status'] = 'parsed';
                statusInfo[sheetNo]['gtiffUrl'] = gtiffInfo.url;
                statusInfo[sheetNo]['gtiffFilesize'] = fsize;
            }
        }

        for (const name in jpgSizeData) {
            const jpgInfo = jpgSizeData[name];
            const sheetNoDisp = name.replace(/_/g, '/').replace('.jpg', '');
            const fsize = fileSize(jpgInfo.size);
            const sheetNumbers = getSheetNumbers(sheetNoDisp);
            
            for (const sheetNo of sheetNumbers) {
                if (!(sheetNo in statusInfo)) {
                    statusInfo[sheetNo] = {};
                }
                statusInfo[sheetNo]['jpgUrl'] = jpgInfo.url;
                statusInfo[sheetNo]['jpgFilesize'] = fsize;
            }
        }
        cb(null, statusInfo)
    }

    fetchSheetList('/india_topo_maps/50k/osm/tiff_listing.csv', (e, results) => {
        if (e) {
            err = e;
        }
        gtiffSizeData = results
        console.log('gtiff data callback invoked')
        collate()
    })

    fetchSheetList('/india_topo_maps/50k/osm/pdf_listing.csv', (e, results) => {
        if (e) {
            err = e;
        }
        pdfSizeData = results
        console.log('pdf data callback invoked')
        collate()
    })

    fetchSheetList('/india_topo_maps/50k/osm/jpg_listing.csv', (e, results) => {
        if (e) {
            err = e;
        }
        jpgSizeData = results
        console.log('jpg data callback invoked')
        collate()
    })

}
