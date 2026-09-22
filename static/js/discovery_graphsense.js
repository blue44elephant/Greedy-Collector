import {element,table,dateText} from './ui.js';
import {sourceReference} from './discovery_manual_source.js';

export function graphSenseDetail(snapshot,retrievedAt) {
  const node=element('section',undefined,'graphsense-detail'),tag=snapshot.tag||{};
  node.append(element('h3','GraphSense public tag'),element('p','Third-party public annotation. GC has not independently verified the attribution. A tag does not prove current control, beneficial or legal ownership.','bounded-note'),
    table(['Field','Published source metadata'],[
      ['Label',tag.label],['Category',tag.category],['Confidence (GraphSense metadata only)',tag.confidence],
      ['Actor (metadata only)',tag.actor],['Cluster definer (metadata only)',tag.is_cluster_definer],
      ['Currency',tag.currency],['Network',tag.network],['TagPack',tag.title],['Creator',tag.creator],
      ['Last modified (source)',tag.lastmod],['Source pointer',tag.source],['Repository',snapshot.repository],
      ['File',snapshot.file_path],['Blob SHA',snapshot.blob_sha],['Ref observed',snapshot.ref],['Retrieved',dateText(retrievedAt)]
    ]),element('p','Confidence is not an Attribution assessment, risk score or ownership probability. Actor and cluster-definer metadata never create Entities, wallet links or clusters.','muted small'));
  if(tag.source_url)node.append(element('h4','Published source (not fetched)'),sourceReference(tag.source_url));
  if(snapshot.file_html_url)node.append(element('h4','Repository provenance'),sourceReference(snapshot.file_html_url));
  return node;
}
